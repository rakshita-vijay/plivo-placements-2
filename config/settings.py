"""Central configuration.

Every environment variable the app reads is declared here, so there is exactly
one place to look when something is misconfigured.
"""

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


class MissingConfigurationError(RuntimeError):
    """Raised at startup when a required environment variable is absent."""


def _read_required(variable_name: str) -> str:
    value = os.environ.get(variable_name, "").strip()
    if not value:
        raise MissingConfigurationError(
            f"Required environment variable {variable_name} is not set. "
            f"Copy .env.example to .env and fill it in."
        )
    return value


def _read_optional(variable_name: str, default: str) -> str:
    value = os.environ.get(variable_name, "").strip()
    return value or default


def _read_int(variable_name: str, default: int) -> int:
    raw_value = os.environ.get(variable_name, "").strip()
    if not raw_value:
        return default
    try:
        return int(raw_value)
    except ValueError as error:
        raise MissingConfigurationError(
            f"{variable_name} must be an integer, got {raw_value!r}"
        ) from error


def _read_float(variable_name: str, default: float) -> float:
    raw_value = os.environ.get(variable_name, "").strip()
    if not raw_value:
        return default
    try:
        return float(raw_value)
    except ValueError as error:
        raise MissingConfigurationError(
            f"{variable_name} must be a number, got {raw_value!r}"
        ) from error


@dataclass(frozen=True)
class Settings:
    # --- Slack ---
    slack_bot_token: str
    slack_app_token: str

    # --- Replicate ---
    replicate_api_token: str
    lora_model_version: str
    lora_trigger_word: str

    # --- Image generation knobs ---
    image_aspect_ratio: str = "1:1"
    image_output_format: str = "jpg"
    image_inference_steps: int = 28
    image_guidance_scale: float = 3.0
    lora_scale: float = 1.0

    # --- Runtime behaviour ---
    worker_thread_count: int = 4
    prediction_timeout_seconds: int = 300
    prediction_poll_interval_seconds: float = 2.0
    database_path: str = "memory_lane_jobs.db"
    log_level: str = "INFO"

    # --- Training (offline, not used by the live bot) ---
    lora_trainer_version: str = field(
        default=(
            "ostris/flux-dev-lora-trainer:"
            "e440909d3512c31646ee2e0c7d6f6f4923224863a6a10c494606e79fb5844497"
        )
    )
    lora_destination_model: str = ""


def load_settings() -> Settings:
    """Read configuration from the environment. Fails loudly and early."""
    return Settings(
        slack_bot_token=_read_required("SLACK_BOT_TOKEN"),
        slack_app_token=_read_required("SLACK_APP_TOKEN"),
        replicate_api_token=_read_required("REPLICATE_API_TOKEN"),
        lora_model_version=_read_required("LORA_MODEL_VERSION"),
        lora_trigger_word=_read_optional("LORA_TRIGGER_WORD", "TOK"),
        image_aspect_ratio=_read_optional("IMAGE_ASPECT_RATIO", "1:1"),
        image_output_format=_read_optional("IMAGE_OUTPUT_FORMAT", "jpg"),
        image_inference_steps=_read_int("IMAGE_INFERENCE_STEPS", 28),
        image_guidance_scale=_read_float("IMAGE_GUIDANCE_SCALE", 3.0),
        lora_scale=_read_float("LORA_SCALE", 1.0),
        worker_thread_count=_read_int("WORKER_THREAD_COUNT", 4),
        prediction_timeout_seconds=_read_int("PREDICTION_TIMEOUT_SECONDS", 300),
        prediction_poll_interval_seconds=_read_float(
            "PREDICTION_POLL_INTERVAL_SECONDS", 2.0
        ),
        database_path=_read_optional("DATABASE_PATH", "memory_lane_jobs.db"),
        log_level=_read_optional("LOG_LEVEL", "INFO"),
        lora_trainer_version=_read_optional(
            "LORA_TRAINER_VERSION",
            "ostris/flux-dev-lora-trainer:"
            "e440909d3512c31646ee2e0c7d6f6f4923224863a6a10c494606e79fb5844497",
        ),
        lora_destination_model=_read_optional("LORA_DESTINATION_MODEL", ""),
    )
