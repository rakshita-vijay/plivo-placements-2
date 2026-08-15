"""The background half of the bot.

Slack listeners must return in under three seconds. So a listener does only
cheap work (parse, persist, post an acknowledgement) and then hands the job to
this worker, which owns the slow parts: Replicate inference, downloading the
result, and uploading it back into the originating thread.
"""

import logging
from concurrent.futures import ThreadPoolExecutor

import requests

from core.prompt_parser import PhotoRequest
from replicate_client.inference import (
    FluxLoraInferenceClient,
    ReplicateInferenceError,
    ReplicateRateLimitError,
    ReplicateTimeoutError,
)
from slack_app import messages
from store.job_store import Job, JobStore

logger = logging.getLogger(__name__)

IMAGE_DOWNLOAD_TIMEOUT_SECONDS = 60


class PhotoRequestWorker:
    """Runs generation jobs off the Slack event thread."""

    def __init__(
        self,
        slack_web_client,
        inference_client: FluxLoraInferenceClient,
        job_store: JobStore,
        worker_thread_count: int = 4,
    ):
        self.slack_web_client = slack_web_client
        self.inference_client = inference_client
        self.job_store = job_store
        self.thread_pool = ThreadPoolExecutor(
            max_workers=worker_thread_count,
            thread_name_prefix="photo-worker",
        )

    def submit(self, job: Job, photo_request: PhotoRequest) -> None:
        """Queue a job. Returns immediately."""
        self.thread_pool.submit(self._run_job_safely, job, photo_request)

    def shutdown(self) -> None:
        self.thread_pool.shutdown(wait=False, cancel_futures=True)

    # ------------------------------------------------------------------
    def _run_job_safely(self, job: Job, photo_request: PhotoRequest) -> None:
        """Never let an exception escape into the thread pool unlogged."""
        try:
            self._run_job(job, photo_request)
        except Exception:
            logger.exception("Unhandled error in job %s", job.job_id)
            self.job_store.mark_failed(job.job_id, "Unexpected internal error.")
            self._post_in_thread(
                job,
                messages.generation_failed_text(
                    job.job_id, "Unexpected internal error."
                ),
            )

    def _run_job(self, job: Job, photo_request: PhotoRequest) -> None:
        logger.info("Job %s starting: %r", job.job_id, photo_request.generation_prompt)

        try:
            generated_image = self.inference_client.generate_image(
                photo_request.generation_prompt,
                on_prediction_created=lambda prediction_id: (
                    self.job_store.mark_submitted(job.job_id, prediction_id)
                ),
            )
        except ReplicateRateLimitError as error:
            logger.warning("Job %s rate limited: %s", job.job_id, error)
            self.job_store.mark_failed(job.job_id, "Rate limited by Replicate.")
            self._post_in_thread(job, messages.replicate_rate_limited_text())
            return
        except ReplicateTimeoutError as error:
            logger.warning("Job %s timed out: %s", job.job_id, error)
            self.job_store.mark_timed_out(job.job_id, str(error))
            self._post_in_thread(
                job,
                messages.generation_timed_out_text(
                    job.job_id, self.inference_client.timeout_seconds
                ),
            )
            return
        except ReplicateInferenceError as error:
            logger.warning("Job %s failed: %s", job.job_id, error)
            self.job_store.mark_failed(job.job_id, str(error))
            self._post_in_thread(
                job, messages.generation_failed_text(job.job_id, str(error))
            )
            return

        self.job_store.mark_succeeded(job.job_id, generated_image.image_url)
        caption = messages.success_caption(
            photo_request.age_in_years,
            photo_request.scene,
            generated_image.seconds_elapsed,
        )
        self._deliver_image(job, generated_image.image_url, caption)
        logger.info(
            "Job %s delivered in %.1fs", job.job_id, generated_image.seconds_elapsed
        )

    # ------------------------------------------------------------------
    def _deliver_image(self, job: Job, image_url: str, caption: str) -> None:
        """Upload the image into the thread.

        Preferred path is a real file upload so the image lives in Slack.
        Replicate's CDN links expire within the hour, so posting the raw link
        is only a fallback.
        """
        try:
            image_bytes = self._download_image(image_url)
            self.slack_web_client.files_upload_v2(
                channel=job.slack_channel_id,
                thread_ts=job.slack_thread_ts,
                file=image_bytes,
                filename=f"memory-lane-{job.job_id}.jpg",
                title="Down Memory Lane",
                initial_comment=caption,
            )
            return
        except Exception as error:
            logger.warning(
                "Upload failed for job %s (%s); falling back to link",
                job.job_id,
                error,
            )

        self._post_in_thread(
            job,
            f"{caption}\n{image_url}\n_(link expires within the hour)_",
        )

    @staticmethod
    def _download_image(image_url: str) -> bytes:
        response = requests.get(image_url, timeout=IMAGE_DOWNLOAD_TIMEOUT_SECONDS)
        response.raise_for_status()
        return response.content

    def _post_in_thread(self, job: Job, text: str) -> None:
        """Every reply goes back to the thread the request came from."""
        try:
            self.slack_web_client.chat_postMessage(
                channel=job.slack_channel_id,
                thread_ts=job.slack_thread_ts,
                text=text,
            )
        except Exception:
            logger.exception("Could not post to %s", job.slack_channel_id)
