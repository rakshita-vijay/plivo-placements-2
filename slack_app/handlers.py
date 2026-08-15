"""Slack event listeners.

Rule for everything in this file: do only fast work. Parse the text, write a
row, post one acknowledgement, hand off to the worker, return. Bolt acks the
event to Slack before the listener body runs, and the listener itself finishes
in well under a second, so we never approach Slack's 3-second limit.
"""

import logging

from slack_bolt import App

from core.prompt_parser import UnparseableRequestError, parse_photo_request
from slack_app import messages
from slack_app.photo_request_worker import PhotoRequestWorker
from store.job_store import JobStore

logger = logging.getLogger(__name__)

MAXIMUM_CONCURRENT_JOBS_PER_USER = 3
HELP_KEYWORDS = {"help", "?", "hi", "hello", "usage"}


def _strip_bot_mention(message_text: str, bot_user_id: str) -> str:
    if not bot_user_id:
        return message_text
    return message_text.replace(f"<@{bot_user_id}>", " ").strip()


def _resolve_thread_ts(event: dict) -> str:
    """Reply into the existing thread if there is one, otherwise start a thread
    hanging off the message we were mentioned in."""
    return event.get("thread_ts") or event["ts"]


def _is_from_a_bot(event: dict) -> bool:
    """True for anything posted by this bot or any other app.

    Without this, one bot mentioning another can start a loop that generates
    images (and spends money) with no human involved.
    """
    return bool(
        event.get("bot_id")
        or event.get("bot_profile")
        or event.get("subtype") == "bot_message"
    )


def register_handlers(
    app: App,
    job_store: JobStore,
    worker: PhotoRequestWorker,
    trigger_word: str,
) -> None:
    """Attach all listeners to the Bolt app."""

    def handle_photo_request(event: dict, say, client) -> None:
        if _is_from_a_bot(event):
            logger.debug("Ignoring message from a bot: %s", event.get("bot_id"))
            return

        slack_user_id = event.get("user", "")
        slack_channel_id = event["channel"]
        thread_ts = _resolve_thread_ts(event)

        # Slack retries deliveries it believes we missed. Only act once.
        slack_event_id = event.get("client_msg_id") or event.get("ts", "")
        if not job_store.claim_slack_event(slack_event_id):
            logger.info("Ignoring duplicate Slack event %s", slack_event_id)
            return

        bot_user_id = client.auth_test().get("user_id", "")
        if slack_user_id and slack_user_id == bot_user_id:
            return  # belt and braces: never answer ourselves

        request_text = _strip_bot_mention(event.get("text", ""), bot_user_id)

        if not request_text or request_text.lower().strip(" ?!.") in HELP_KEYWORDS:
            say(text=messages.HELP_TEXT, thread_ts=thread_ts)
            return

        try:
            photo_request = parse_photo_request(request_text, trigger_word)
        except UnparseableRequestError as error:
            say(text=messages.unparseable_text(error.reason), thread_ts=thread_ts)
            return

        # One image at a time per thread. See README 'Judgment calls' for why
        # this rejects rather than queues.
        job_already_running = job_store.find_active_job_in_thread(
            slack_channel_id, thread_ts
        )
        if job_already_running:
            say(
                text=messages.thread_already_busy_text(job_already_running.job_id),
                thread_ts=thread_ts,
            )
            return

        active_job_count = job_store.count_active_jobs_for_user(slack_user_id)
        if active_job_count >= MAXIMUM_CONCURRENT_JOBS_PER_USER:
            say(
                text=messages.rate_limited_text(active_job_count),
                thread_ts=thread_ts,
            )
            return

        job = job_store.create_job(
            slack_channel_id=slack_channel_id,
            slack_thread_ts=thread_ts,
            slack_user_id=slack_user_id,
            original_text=request_text,
            generation_prompt=photo_request.generation_prompt,
        )
        logger.info(
            "Queued job %s for user %s in %s/%s",
            job.job_id, slack_user_id, slack_channel_id, thread_ts,
        )

        say(
            text=messages.acknowledgement_text(
                photo_request.age_in_years,
                photo_request.scene,
                photo_request.age_was_specified,
            ),
            thread_ts=thread_ts,
        )
        worker.submit(job, photo_request)

    @app.event("app_mention")
    def on_app_mention(event, say, client):
        handle_photo_request(event, say, client)

    @app.event("message")
    def on_direct_message(event, say, client):
        """Direct messages need no mention; channel messages are handled by
        app_mention so we don't respond to every line of chatter.

        The bot check in handle_photo_request covers loops; the subtype check
        here additionally skips joins, edits, and file-share events."""
        is_direct_message = event.get("channel_type") == "im"
        if is_direct_message and event.get("subtype") is None:
            handle_photo_request(event, say, client)

    @app.error
    def on_unhandled_error(error, body):
        logger.exception("Unhandled Bolt error: %s | body=%s", error, body)
