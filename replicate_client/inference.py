"""Replicate inference: run the trained Flux LoRA and return an image URL.

We deliberately use the low-level predictions API (create + poll) rather than
`replicate.run()`, because we need to own the timeout and to record the
prediction id in our store while the job is still running.
"""

import logging
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

import replicate
from replicate.client import Client

logger = logging.getLogger(__name__)

TERMINAL_SUCCESS_STATUS = "succeeded"
TOO_MANY_REQUESTS_STATUS = 429
TERMINAL_FAILURE_STATUSES = {"failed", "canceled"}


class ReplicateInferenceError(RuntimeError):
    """Replicate accepted the job but it did not produce an image."""


class ReplicateRateLimitError(RuntimeError):
    """Replicate returned HTTP 429. The request was not started; retrying later
    is the correct response, so this is kept distinct from a real failure."""


class ReplicateTimeoutError(RuntimeError):
    """The prediction did not reach a terminal state within our time budget."""


# HTTP statuses worth translating into something a human can act on. Anything
# not listed here falls through to the generic failure message.
_API_ERROR_EXPLANATIONS = {
    401: "Replicate rejected our API token. Check REPLICATE_API_TOKEN.",
    402: "The Replicate account is out of credit or has hit its spend limit.",
    403: "This Replicate token is not allowed to run that model.",
    404: (
        "Replicate could not find that model version. "
        "Check LORA_MODEL_VERSION."
    ),
    422: "Replicate rejected the inputs for this model version.",
}


def _describe_api_error(error) -> str:
    """Turn a ReplicateError into something worth putting in front of a user."""
    status_code = getattr(error, "status", None)
    explanation = _API_ERROR_EXPLANATIONS.get(status_code)
    detail = getattr(error, "detail", None) or str(error)
    if explanation:
        return f"{explanation} ({detail})"
    return f"Replicate rejected the request: {detail}"


@dataclass
class GeneratedImage:
    image_url: str
    prediction_id: str
    seconds_elapsed: float


def _extract_first_image_url(prediction_output: Any) -> Optional[str]:
    """Flux models return a list of file objects or URL strings; sometimes a
    bare string. Normalise all of those to a single URL."""
    if prediction_output is None:
        return None
    if isinstance(prediction_output, str):
        return prediction_output
    if isinstance(prediction_output, (list, tuple)):
        if not prediction_output:
            return None
        return _extract_first_image_url(prediction_output[0])
    # replicate.helpers.FileOutput and friends expose .url, or stringify to it.
    url_attribute = getattr(prediction_output, "url", None)
    if isinstance(url_attribute, str):
        return url_attribute
    text_value = str(prediction_output)
    return text_value if text_value.startswith("http") else None


class FluxLoraInferenceClient:
    """Thin wrapper around the Replicate predictions API for our LoRA."""

    def __init__(
        self,
        api_token: str,
        model_version: str,
        aspect_ratio: str = "1:1",
        output_format: str = "jpg",
        inference_steps: int = 28,
        guidance_scale: float = 3.0,
        lora_scale: float = 1.0,
        timeout_seconds: int = 300,
        poll_interval_seconds: float = 2.0,
    ):
        self.client = Client(api_token=api_token)
        self.model_version = model_version
        self.aspect_ratio = aspect_ratio
        self.output_format = output_format
        self.inference_steps = inference_steps
        self.guidance_scale = guidance_scale
        self.lora_scale = lora_scale
        self.timeout_seconds = timeout_seconds
        self.poll_interval_seconds = poll_interval_seconds

    def _version_identifier(self) -> str:
        """Accept either a bare version hash or 'owner/model:hash'."""
        if ":" in self.model_version:
            return self.model_version.split(":", 1)[1]
        return self.model_version

    def build_model_input(self, generation_prompt: str) -> dict:
        return {
            "prompt": generation_prompt,
            "num_outputs": 1,
            "aspect_ratio": self.aspect_ratio,
            "output_format": self.output_format,
            "output_quality": 90,
            "num_inference_steps": self.inference_steps,
            "guidance_scale": self.guidance_scale,
            "lora_scale": self.lora_scale,
            "go_fast": False,
            "megapixels": "1",
            "disable_safety_checker": False,
        }

    def generate_image(
        self,
        generation_prompt: str,
        on_prediction_created: Optional[Callable[[str], None]] = None,
    ) -> GeneratedImage:
        """Submit a prediction and block until it produces an image.

        `on_prediction_created` fires as soon as Replicate returns an id, so the
        caller can persist it before the (slow) polling loop begins.
        """
        started_at = time.monotonic()

        try:
            prediction = self.client.predictions.create(
                version=self._version_identifier(),
                input=self.build_model_input(generation_prompt),
            )
        except replicate.exceptions.ReplicateError as error:
            if getattr(error, "status", None) == TOO_MANY_REQUESTS_STATUS:
                raise ReplicateRateLimitError(
                    "Replicate is rate limiting us."
                ) from error
            raise ReplicateInferenceError(_describe_api_error(error)) from error
        except Exception as error:  # network failures, DNS, TLS, ...
            raise ReplicateInferenceError(
                f"Could not reach Replicate: {error}"
            ) from error

        logger.info(
            "Created prediction %s for prompt %r",
            prediction.id,
            generation_prompt[:80],
        )
        if on_prediction_created:
            on_prediction_created(prediction.id)

        return self._poll_until_finished(prediction, started_at)

    def _poll_until_finished(self, prediction, started_at: float) -> GeneratedImage:
        while True:
            if prediction.status == TERMINAL_SUCCESS_STATUS:
                image_url = _extract_first_image_url(prediction.output)
                if not image_url:
                    raise ReplicateInferenceError(
                        "Prediction succeeded but returned no image URL."
                    )
                return GeneratedImage(
                    image_url=image_url,
                    prediction_id=prediction.id,
                    seconds_elapsed=round(time.monotonic() - started_at, 1),
                )

            if prediction.status in TERMINAL_FAILURE_STATUSES:
                raise ReplicateInferenceError(
                    f"Prediction {prediction.id} {prediction.status}: "
                    f"{prediction.error or 'no error detail provided'}"
                )

            if time.monotonic() - started_at > self.timeout_seconds:
                self._cancel_quietly(prediction)
                raise ReplicateTimeoutError(
                    f"Prediction {prediction.id} did not finish within "
                    f"{self.timeout_seconds}s (last status: {prediction.status})."
                )

            time.sleep(self.poll_interval_seconds)
            try:
                prediction.reload()
            except replicate.exceptions.ReplicateError as error:
                if getattr(error, "status", None) == TOO_MANY_REQUESTS_STATUS:
                    # The prediction is already running on Replicate's side; a
                    # throttled status check is not a reason to abandon it.
                    # The timeout ceiling above still bounds this loop.
                    logger.warning(
                        "Rate limited while polling %s; will check again.",
                        prediction.id,
                    )
                    continue
                raise ReplicateInferenceError(
                    _describe_api_error(error)
                ) from error
            except Exception as error:
                raise ReplicateInferenceError(
                    f"Lost contact with Replicate while polling "
                    f"{prediction.id}: {error}"
                ) from error

    @staticmethod
    def _cancel_quietly(prediction) -> None:
        """Stop paying for a prediction we have already given up on."""
        try:
            prediction.cancel()
        except Exception:
            logger.warning("Could not cancel prediction %s", prediction.id)
