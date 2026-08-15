"""End-to-end test of the Slack listener -> worker -> Slack reply path.

Slack and Replicate are both mocked, so this runs offline. It verifies the
behaviour that actually matters in production: the reply lands in the right
thread, duplicates are ignored, and failures still produce a human answer.
"""

import os
import sys
import tempfile
import time
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.prompt_parser import parse_photo_request  # noqa: E402
from replicate_client.inference import (  # noqa: E402
    GeneratedImage,
    ReplicateInferenceError,
    ReplicateRateLimitError,
    ReplicateTimeoutError,
)
from slack_app.handlers import register_handlers  # noqa: E402
from slack_app.photo_request_worker import PhotoRequestWorker  # noqa: E402
from store.job_store import JobStore, JobStatus  # noqa: E402

BOT_USER_ID = "U0BOT"
CHANNEL_ID = "C123"
PARENT_MESSAGE_TS = "1700000000.000100"


class FakeBoltApp:
    """Captures listeners registered by register_handlers so tests can fire them."""

    def __init__(self):
        self.event_listeners = {}
        self.client = MagicMock()
        self.client.auth_test.return_value = {"user_id": BOT_USER_ID}

    def event(self, event_name):
        def decorator(function):
            self.event_listeners[event_name] = function
            return function
        return decorator

    def error(self, function):
        return function


@pytest.fixture
def harness():
    database_path = os.path.join(tempfile.mkdtemp(), "jobs.db")
    job_store = JobStore(database_path)
    fake_app = FakeBoltApp()
    inference_client = MagicMock()
    inference_client.timeout_seconds = 300

    worker = PhotoRequestWorker(
        slack_web_client=fake_app.client,
        inference_client=inference_client,
        job_store=job_store,
        worker_thread_count=2,
    )
    register_handlers(fake_app, job_store, worker, trigger_word="TOK")

    sent_messages = []

    def fake_say(text, thread_ts=None):
        sent_messages.append({"text": text, "thread_ts": thread_ts})

    yield {
        "app": fake_app,
        "store": job_store,
        "worker": worker,
        "inference": inference_client,
        "say": fake_say,
        "sent": sent_messages,
    }
    worker.shutdown()


def make_event(text, ts=PARENT_MESSAGE_TS, thread_ts=None, client_msg_id="m1"):
    event = {
        "type": "app_mention",
        "user": "U_HUMAN",
        "channel": CHANNEL_ID,
        "text": f"<@{BOT_USER_ID}> {text}",
        "ts": ts,
        "client_msg_id": client_msg_id,
    }
    if thread_ts:
        event["thread_ts"] = thread_ts
    return event


def wait_for_worker(worker, timeout=5.0):
    deadline = time.time() + timeout
    while worker.thread_pool._work_queue.qsize() > 0 and time.time() < deadline:
        time.sleep(0.02)
    time.sleep(0.3)


def test_happy_path_replies_in_same_thread(harness):
    def generate_and_report_id(prompt, on_prediction_created=None):
        # The real client calls this as soon as Replicate returns an id.
        if on_prediction_created:
            on_prediction_created("pred_1")
        return GeneratedImage(
            image_url="https://cdn.replicate/out.jpg",
            prediction_id="pred_1",
            seconds_elapsed=42.0,
        )

    harness["inference"].generate_image.side_effect = generate_and_report_id
    with patch(
        "slack_app.photo_request_worker.PhotoRequestWorker._download_image",
        return_value=b"fake-jpeg-bytes",
    ):
        listener = harness["app"].event_listeners["app_mention"]
        listener(
            make_event("my 5-year-old self on a beach"),
            harness["say"],
            harness["app"].client,
        )
        wait_for_worker(harness["worker"])

    # 1. Acknowledgement posted immediately, in-thread.
    assert len(harness["sent"]) == 1
    assert "Working on it" in harness["sent"][0]["text"]
    assert harness["sent"][0]["thread_ts"] == PARENT_MESSAGE_TS

    # 2. Image uploaded to the SAME thread.
    upload_call = harness["app"].client.files_upload_v2.call_args.kwargs
    assert upload_call["channel"] == CHANNEL_ID
    assert upload_call["thread_ts"] == PARENT_MESSAGE_TS
    assert upload_call["file"] == b"fake-jpeg-bytes"
    assert "You at 5" in upload_call["initial_comment"]

    # 3. Job recorded as succeeded.
    job = harness["store"].list_recent_jobs()[0]
    assert job.status == JobStatus.SUCCEEDED.value
    assert job.prediction_id == "pred_1"
    assert "TOK" in job.generation_prompt


def test_reply_goes_to_existing_thread_not_channel_root(harness):
    existing_thread_ts = "1699999999.000001"
    harness["inference"].generate_image.return_value = GeneratedImage(
        "https://cdn/out.jpg", "pred_2", 10.0
    )
    with patch(
        "slack_app.photo_request_worker.PhotoRequestWorker._download_image",
        return_value=b"x",
    ):
        listener = harness["app"].event_listeners["app_mention"]
        listener(
            make_event("my 10-year-old self in a classroom",
                       ts="1700000000.000999",
                       thread_ts=existing_thread_ts),
            harness["say"],
            harness["app"].client,
        )
        wait_for_worker(harness["worker"])

    assert harness["sent"][0]["thread_ts"] == existing_thread_ts
    assert (harness["app"].client.files_upload_v2.call_args.kwargs["thread_ts"]
            == existing_thread_ts)


def test_duplicate_slack_delivery_is_ignored(harness):
    harness["inference"].generate_image.return_value = GeneratedImage(
        "https://cdn/out.jpg", "pred_3", 5.0
    )
    with patch(
        "slack_app.photo_request_worker.PhotoRequestWorker._download_image",
        return_value=b"x",
    ):
        listener = harness["app"].event_listeners["app_mention"]
        event = make_event("my 2-year-old self in the backyard", client_msg_id="dup-1")
        listener(event, harness["say"], harness["app"].client)
        listener(event, harness["say"], harness["app"].client)
        wait_for_worker(harness["worker"])

    assert len(harness["store"].list_recent_jobs()) == 1
    assert harness["inference"].generate_image.call_count == 1


def test_malformed_request_gets_guidance_not_a_job(harness):
    listener = harness["app"].event_listeners["app_mention"]
    listener(make_event(""), harness["say"], harness["app"].client)
    assert "Down Memory Lane" in harness["sent"][0]["text"]
    assert harness["store"].list_recent_jobs() == []


def test_replicate_failure_is_reported_in_thread(harness):
    harness["inference"].generate_image.side_effect = ReplicateInferenceError(
        "Prediction pred_x failed: NSFW content detected"
    )
    listener = harness["app"].event_listeners["app_mention"]
    listener(
        make_event("my 7-year-old self on a swing"),
        harness["say"],
        harness["app"].client,
    )
    wait_for_worker(harness["worker"])

    posted = harness["app"].client.chat_postMessage.call_args.kwargs
    assert posted["thread_ts"] == PARENT_MESSAGE_TS
    assert "couldn't generate" in posted["text"]
    assert harness["store"].list_recent_jobs()[0].status == JobStatus.FAILED.value


def test_timeout_is_reported_in_thread(harness):
    harness["inference"].generate_image.side_effect = ReplicateTimeoutError(
        "Prediction pred_y did not finish within 300s"
    )
    listener = harness["app"].event_listeners["app_mention"]
    listener(
        make_event("my 9-year-old self at a birthday party"),
        harness["say"],
        harness["app"].client,
    )
    wait_for_worker(harness["worker"])

    posted = harness["app"].client.chat_postMessage.call_args.kwargs
    assert "stopped waiting" in posted["text"]
    assert harness["store"].list_recent_jobs()[0].status == JobStatus.TIMED_OUT.value


def test_upload_failure_falls_back_to_posting_the_link(harness):
    harness["inference"].generate_image.return_value = GeneratedImage(
        "https://cdn/fallback.jpg", "pred_z", 8.0
    )
    harness["app"].client.files_upload_v2.side_effect = Exception("missing_scope")
    with patch(
        "slack_app.photo_request_worker.PhotoRequestWorker._download_image",
        return_value=b"x",
    ):
        listener = harness["app"].event_listeners["app_mention"]
        listener(
            make_event("my 6-year-old self in a park"),
            harness["say"],
            harness["app"].client,
        )
        wait_for_worker(harness["worker"])

    posted = harness["app"].client.chat_postMessage.call_args.kwargs
    assert "https://cdn/fallback.jpg" in posted["text"]
    assert posted["thread_ts"] == PARENT_MESSAGE_TS


def test_concurrent_requests_in_different_threads_do_not_collide(harness):
    thread_ids = ["1700000001.0001", "1700000002.0002", "1700000003.0003"]

    def slow_generation(prompt, on_prediction_created=None):
        if on_prediction_created:
            on_prediction_created("pred_" + prompt[-6:])
        time.sleep(0.2)
        return GeneratedImage(f"https://cdn/{prompt[-6:]}.jpg", "pred", 1.0)

    harness["inference"].generate_image.side_effect = slow_generation
    with patch(
        "slack_app.photo_request_worker.PhotoRequestWorker._download_image",
        return_value=b"x",
    ):
        listener = harness["app"].event_listeners["app_mention"]
        for index, thread_id in enumerate(thread_ids):
            listener(
                make_event(
                    f"my {index + 3}-year-old self in scene number {index}",
                    ts=thread_id,
                    client_msg_id=f"msg-{index}",
                ),
                harness["say"],
                harness["app"].client,
            )
        wait_for_worker(harness["worker"], timeout=10)

    uploaded_thread_ts = {
        call.kwargs["thread_ts"]
        for call in harness["app"].client.files_upload_v2.call_args_list
    }
    assert uploaded_thread_ts == set(thread_ids)
    assert len(harness["store"].list_recent_jobs()) == 3


def test_messages_from_bots_are_ignored(harness):
    """A bot mentioning our bot must not start a generation loop."""
    listener = harness["app"].event_listeners["app_mention"]
    for bot_marker in (
        {"bot_id": "B0999"},
        {"bot_profile": {"id": "B0999", "name": "Zapier"}},
        {"subtype": "bot_message"},
    ):
        event = make_event("my 5-year-old self on a beach",
                           client_msg_id=f"bot-{list(bot_marker)[0]}")
        event.update(bot_marker)
        listener(event, harness["say"], harness["app"].client)

    assert harness["sent"] == []
    assert harness["store"].list_recent_jobs() == []
    assert harness["inference"].generate_image.call_count == 0


def test_second_request_in_same_thread_is_rejected_not_queued(harness):
    def slow_generation(prompt, on_prediction_created=None):
        time.sleep(1.0)
        return GeneratedImage("https://cdn/x.jpg", "pred", 1.0)

    harness["inference"].generate_image.side_effect = slow_generation
    listener = harness["app"].event_listeners["app_mention"]
    with patch(
        "slack_app.photo_request_worker.PhotoRequestWorker._download_image",
        return_value=b"x",
    ):
        listener(
            make_event("my 5-year-old self on a beach", client_msg_id="first"),
            harness["say"], harness["app"].client,
        )
        listener(
            make_event("my 8-year-old self in a park",
                       thread_ts=PARENT_MESSAGE_TS, client_msg_id="second"),
            harness["say"], harness["app"].client,
        )

        # Only the first became a job; the second got told to wait.
        assert len(harness["store"].list_recent_jobs()) == 1
        assert "still working on your last request" in harness["sent"][1]["text"]
        assert harness["sent"][1]["thread_ts"] == PARENT_MESSAGE_TS
        wait_for_worker(harness["worker"], timeout=10)


def test_thread_accepts_a_new_request_once_the_first_finishes(harness):
    harness["inference"].generate_image.return_value = GeneratedImage(
        "https://cdn/x.jpg", "pred", 1.0
    )
    listener = harness["app"].event_listeners["app_mention"]
    with patch(
        "slack_app.photo_request_worker.PhotoRequestWorker._download_image",
        return_value=b"x",
    ):
        listener(
            make_event("my 5-year-old self on a beach", client_msg_id="one"),
            harness["say"], harness["app"].client,
        )
        wait_for_worker(harness["worker"])
        listener(
            make_event("my 8-year-old self in a park",
                       thread_ts=PARENT_MESSAGE_TS, client_msg_id="two"),
            harness["say"], harness["app"].client,
        )
        wait_for_worker(harness["worker"])

    assert len(harness["store"].list_recent_jobs()) == 2
    assert not any("still working" in message["text"]
                   for message in harness["sent"])


def test_replicate_rate_limit_gets_a_friendly_message(harness):
    harness["inference"].generate_image.side_effect = ReplicateRateLimitError(
        "Replicate is rate limiting us."
    )
    listener = harness["app"].event_listeners["app_mention"]
    listener(
        make_event("my 5-year-old self on a beach"),
        harness["say"], harness["app"].client,
    )
    wait_for_worker(harness["worker"])

    posted = harness["app"].client.chat_postMessage.call_args.kwargs
    assert "busy right now" in posted["text"]
    assert "429" not in posted["text"]
    assert posted["thread_ts"] == PARENT_MESSAGE_TS


def test_per_user_concurrency_limit_blocks_the_fourth_request(harness):
    def still_running(prompt, on_prediction_created=None):
        time.sleep(1.5)
        return GeneratedImage("https://cdn/x.jpg", "p", 1.0)

    harness["inference"].generate_image.side_effect = still_running
    with patch(
        "slack_app.photo_request_worker.PhotoRequestWorker._download_image",
        return_value=b"x",
    ):
        listener = harness["app"].event_listeners["app_mention"]
        for index in range(4):
            listener(
                make_event(
                    f"my 5-year-old self in place {index}",
                    ts=f"17000001.000{index}",
                    client_msg_id=f"limit-{index}",
                ),
                harness["say"],
                harness["app"].client,
            )

        assert any("already have" in message["text"] for message in harness["sent"])
        assert len(harness["store"].list_recent_jobs()) == 3
        wait_for_worker(harness["worker"], timeout=10)
