"""Stage 2 smoke test: prove Replicate inference works before wiring it to Slack.

    python scripts/stage2_test_inference.py
    python scripts/stage2_test_inference.py "my 5-year-old self on a beach"

Prints the resulting image URL. Open it in a browser to check the likeness.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import MissingConfigurationError, load_settings
from core.prompt_parser import parse_photo_request
from replicate_client.inference import (
    FluxLoraInferenceClient,
    ReplicateInferenceError,
    ReplicateTimeoutError,
)

DEFAULT_TEST_MESSAGE = "my 5-year-old self on a beach"


def main() -> int:
    try:
        settings = load_settings()
    except MissingConfigurationError as error:
        print(f"Configuration error: {error}")
        return 1

    message_text = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_TEST_MESSAGE
    photo_request = parse_photo_request(message_text, settings.lora_trigger_word)

    print(f"Message : {message_text}")
    print(f"Age     : {photo_request.age_in_years} "
          f"(specified: {photo_request.age_was_specified})")
    print(f"Scene   : {photo_request.scene}")
    print(f"Prompt  : {photo_request.generation_prompt}\n")

    inference_client = FluxLoraInferenceClient(
        api_token=settings.replicate_api_token,
        model_version=settings.lora_model_version,
        aspect_ratio=settings.image_aspect_ratio,
        output_format=settings.image_output_format,
        inference_steps=settings.image_inference_steps,
        guidance_scale=settings.image_guidance_scale,
        lora_scale=settings.lora_scale,
        timeout_seconds=settings.prediction_timeout_seconds,
        poll_interval_seconds=settings.prediction_poll_interval_seconds,
    )

    try:
        generated_image = inference_client.generate_image(
            photo_request.generation_prompt,
            on_prediction_created=lambda pid: print(f"Prediction created: {pid}"),
        )
    except (ReplicateInferenceError, ReplicateTimeoutError) as error:
        print(f"\nFAILED: {error}")
        return 1

    print(f"\nSUCCESS in {generated_image.seconds_elapsed}s")
    print(f"Image: {generated_image.image_url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
