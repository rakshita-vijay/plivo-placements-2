import os
import sys
import tempfile
import threading

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from store.job_store import JobStatus, JobStore  # noqa: E402


@pytest.fixture
def job_store():
    return JobStore(os.path.join(tempfile.mkdtemp(), "jobs.db"))


def make_job(job_store, user_id="U1", channel="C1", thread="1700.1"):
    return job_store.create_job(
        slack_channel_id=channel,
        slack_thread_ts=thread,
        slack_user_id=user_id,
        original_text="my 5-year-old self on a beach",
        generation_prompt="A candid photograph of TOK ...",
    )


def test_job_lifecycle(job_store):
    job = make_job(job_store)
    assert job.status == JobStatus.QUEUED.value

    job_store.mark_submitted(job.job_id, "pred_1")
    assert job_store.get_job(job.job_id).status == JobStatus.SUBMITTED.value
    assert job_store.get_job(job.job_id).prediction_id == "pred_1"

    job_store.mark_succeeded(job.job_id, "https://cdn/out.jpg")
    stored = job_store.get_job(job.job_id)
    assert stored.status == JobStatus.SUCCEEDED.value
    assert stored.image_url == "https://cdn/out.jpg"


def test_failure_and_timeout_record_a_reason(job_store):
    failed = make_job(job_store)
    job_store.mark_failed(failed.job_id, "NSFW filter tripped")
    assert job_store.get_job(failed.job_id).status == JobStatus.FAILED.value
    assert "NSFW" in job_store.get_job(failed.job_id).error_message

    timed_out = make_job(job_store)
    job_store.mark_timed_out(timed_out.job_id, "exceeded 300s")
    assert job_store.get_job(timed_out.job_id).status == JobStatus.TIMED_OUT.value


def test_event_claim_is_idempotent(job_store):
    assert job_store.claim_slack_event("Ev123") is True
    assert job_store.claim_slack_event("Ev123") is False
    assert job_store.claim_slack_event("Ev456") is True


def test_active_job_count_only_counts_unfinished_work(job_store):
    first = make_job(job_store, user_id="U1")
    make_job(job_store, user_id="U1")
    make_job(job_store, user_id="U2")
    assert job_store.count_active_jobs_for_user("U1") == 2

    job_store.mark_succeeded(first.job_id, "https://cdn/x.jpg")
    assert job_store.count_active_jobs_for_user("U1") == 1
    assert job_store.count_active_jobs_for_user("U2") == 1


def test_jobs_from_different_threads_stay_separate(job_store):
    first = make_job(job_store, thread="1700.1")
    second = make_job(job_store, thread="1700.2")
    assert first.job_id != second.job_id
    assert job_store.get_job(first.job_id).slack_thread_ts == "1700.1"
    assert job_store.get_job(second.job_id).slack_thread_ts == "1700.2"


def test_concurrent_writes_do_not_corrupt_state(job_store):
    errors = []

    def create_and_finish(index):
        try:
            job = make_job(job_store, user_id=f"U{index}", thread=f"1700.{index}")
            job_store.mark_submitted(job.job_id, f"pred_{index}")
            job_store.mark_succeeded(job.job_id, f"https://cdn/{index}.jpg")
        except Exception as error:  # noqa: BLE001
            errors.append(error)

    threads = [threading.Thread(target=create_and_finish, args=(i,))
               for i in range(25)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    jobs = job_store.list_recent_jobs(limit=100)
    assert len(jobs) == 25
    assert len({job.job_id for job in jobs}) == 25
    assert all(job.status == JobStatus.SUCCEEDED.value for job in jobs)


def test_find_active_job_in_thread(job_store):
    assert job_store.find_active_job_in_thread("C1", "1700.1") is None

    job = make_job(job_store, channel="C1", thread="1700.1")
    found = job_store.find_active_job_in_thread("C1", "1700.1")
    assert found is not None and found.job_id == job.job_id

    # A different thread in the same channel is unaffected.
    assert job_store.find_active_job_in_thread("C1", "1700.2") is None
    # So is the same thread_ts in a different channel.
    assert job_store.find_active_job_in_thread("C2", "1700.1") is None

    job_store.mark_succeeded(job.job_id, "https://cdn/x.jpg")
    assert job_store.find_active_job_in_thread("C1", "1700.1") is None


def test_failed_job_does_not_block_its_thread(job_store):
    job = make_job(job_store, channel="C1", thread="1700.9")
    job_store.mark_failed(job.job_id, "boom")
    assert job_store.find_active_job_in_thread("C1", "1700.9") is None
