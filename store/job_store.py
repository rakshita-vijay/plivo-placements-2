"""Lightweight SQLite store for request state.

Two things are tracked:

1. `jobs`  — one row per photo request, keyed by a generated job id. This is
   what lets several people (or one person in several threads) have requests in
   flight at once without the responses getting crossed: the Slack channel and
   thread_ts travel with the job, so the worker always knows where to reply.

2. `processed_slack_events` — Slack retries event deliveries when it thinks we
   were slow. Recording the event id lets us ignore duplicates instead of
   generating (and billing for) the same image twice.

SQLite is used with a fresh connection per operation, which is the simplest way
to stay safe across the worker threads. For a prototype this is plenty fast.
"""

import enum
import os
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterator, Optional


class JobStatus(str, enum.Enum):
    QUEUED = "queued"
    SUBMITTED = "submitted"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"


@dataclass
class Job:
    job_id: str
    slack_channel_id: str
    slack_thread_ts: str
    slack_user_id: str
    original_text: str
    generation_prompt: str
    status: str
    prediction_id: Optional[str] = None
    image_url: Optional[str] = None
    error_message: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    job_id            TEXT PRIMARY KEY,
    slack_channel_id  TEXT NOT NULL,
    slack_thread_ts   TEXT NOT NULL,
    slack_user_id     TEXT NOT NULL,
    original_text     TEXT NOT NULL,
    generation_prompt TEXT NOT NULL,
    status            TEXT NOT NULL,
    prediction_id     TEXT,
    image_url         TEXT,
    error_message     TEXT,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_jobs_thread
    ON jobs (slack_channel_id, slack_thread_ts);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs (status);

CREATE TABLE IF NOT EXISTS processed_slack_events (
    slack_event_id TEXT PRIMARY KEY,
    seen_at        TEXT NOT NULL
);
"""


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobStore:
    """All reads and writes of request state go through this class."""

    def __init__(self, database_path: str):
        self.database_path = database_path
        self._write_lock = threading.Lock()
        directory = os.path.dirname(os.path.abspath(database_path))
        os.makedirs(directory, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(_SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA journal_mode=WAL")
            yield connection
            connection.commit()
        finally:
            connection.close()

    # ------------------------------------------------------------------
    # De-duplication
    # ------------------------------------------------------------------
    def claim_slack_event(self, slack_event_id: str) -> bool:
        """Return True the first time an event id is seen, False afterwards."""
        if not slack_event_id:
            return True
        with self._write_lock, self._connect() as connection:
            try:
                connection.execute(
                    "INSERT INTO processed_slack_events "
                    "(slack_event_id, seen_at) VALUES (?, ?)",
                    (slack_event_id, _utc_now_iso()),
                )
                return True
            except sqlite3.IntegrityError:
                return False

    # ------------------------------------------------------------------
    # Job lifecycle
    # ------------------------------------------------------------------
    def create_job(
        self,
        slack_channel_id: str,
        slack_thread_ts: str,
        slack_user_id: str,
        original_text: str,
        generation_prompt: str,
    ) -> Job:
        job = Job(
            job_id=uuid.uuid4().hex[:12],
            slack_channel_id=slack_channel_id,
            slack_thread_ts=slack_thread_ts,
            slack_user_id=slack_user_id,
            original_text=original_text,
            generation_prompt=generation_prompt,
            status=JobStatus.QUEUED.value,
            created_at=_utc_now_iso(),
            updated_at=_utc_now_iso(),
        )
        with self._write_lock, self._connect() as connection:
            connection.execute(
                "INSERT INTO jobs (job_id, slack_channel_id, slack_thread_ts, "
                "slack_user_id, original_text, generation_prompt, status, "
                "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    job.job_id,
                    job.slack_channel_id,
                    job.slack_thread_ts,
                    job.slack_user_id,
                    job.original_text,
                    job.generation_prompt,
                    job.status,
                    job.created_at,
                    job.updated_at,
                ),
            )
        return job

    def mark_submitted(self, job_id: str, prediction_id: str) -> None:
        self._update(
            job_id,
            status=JobStatus.SUBMITTED.value,
            prediction_id=prediction_id,
        )

    def mark_succeeded(self, job_id: str, image_url: str) -> None:
        self._update(job_id, status=JobStatus.SUCCEEDED.value, image_url=image_url)

    def mark_failed(self, job_id: str, error_message: str) -> None:
        self._update(
            job_id,
            status=JobStatus.FAILED.value,
            error_message=error_message[:1000],
        )

    def mark_timed_out(self, job_id: str, error_message: str) -> None:
        self._update(
            job_id,
            status=JobStatus.TIMED_OUT.value,
            error_message=error_message[:1000],
        )

    def _update(self, job_id: str, **columns_to_set) -> None:
        columns_to_set["updated_at"] = _utc_now_iso()
        assignments = ", ".join(f"{name} = ?" for name in columns_to_set)
        values = list(columns_to_set.values()) + [job_id]
        with self._write_lock, self._connect() as connection:
            connection.execute(
                f"UPDATE jobs SET {assignments} WHERE job_id = ?", values
            )

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------
    def get_job(self, job_id: str) -> Optional[Job]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
        return Job(**dict(row)) if row else None

    def find_active_job_in_thread(
        self, slack_channel_id: str, slack_thread_ts: str
    ) -> Optional[Job]:
        """The unfinished job for this thread, if there is one.

        This is the thread_ts -> job_id -> status lookup that lets us tell a
        user their previous request is still running, rather than quietly
        starting a second one in the same conversation.
        """
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM jobs "
                "WHERE slack_channel_id = ? AND slack_thread_ts = ? "
                "AND status IN (?, ?) "
                "ORDER BY created_at DESC LIMIT 1",
                (
                    slack_channel_id,
                    slack_thread_ts,
                    JobStatus.QUEUED.value,
                    JobStatus.SUBMITTED.value,
                ),
            ).fetchone()
        return Job(**dict(row)) if row else None

    def count_active_jobs_for_user(self, slack_user_id: str) -> int:
        """How many of this user's requests are still running.

        Used to stop one person queueing twenty images at once.
        """
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS active_count FROM jobs "
                "WHERE slack_user_id = ? AND status IN (?, ?)",
                (slack_user_id, JobStatus.QUEUED.value, JobStatus.SUBMITTED.value),
            ).fetchone()
        return int(row["active_count"])

    def list_recent_jobs(self, limit: int = 20) -> list[Job]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [Job(**dict(row)) for row in rows]
