"""One-off LoRA training against Replicate's Flux trainer.

This is NOT part of the live bot flow. Training takes 15-40 minutes, so it is
run once, ahead of time, and the resulting version id is pasted into
LORA_MODEL_VERSION in .env.

Usage:
    python -m replicate_client.training --photos-zip data/my_photos.zip \\
        --destination your-username/memory-lane-lora \\
        --trigger-word TOK
"""

import argparse
import logging
import os
import sys
import time

from dotenv import load_dotenv
from replicate.client import Client

load_dotenv()

logger = logging.getLogger(__name__)

# Replicate publishes new versions of the trainer periodically. If training
# fails with "version not found", copy the current version id from
# https://replicate.com/ostris/flux-dev-lora-trainer and either pass
# --trainer-version or set LORA_TRAINER_VERSION in .env
DEFAULT_TRAINER_VERSION = os.environ.get("LORA_TRAINER_VERSION", "").strip() or (
    "ostris/flux-dev-lora-trainer:"
    "e440909d3512c31646ee2e0c7d6f6f4923224863a6a10c494606e79fb5844497"
)


def start_training(
    api_token: str,
    photos_zip_path: str,
    destination_model: str,
    trigger_word: str = "TOK",
    training_steps: int = 1000,
    learning_rate: float = 0.0004,
    trainer_version: str = DEFAULT_TRAINER_VERSION,
):
    """Kick off a LoRA fine-tune and return the Training object.

    `destination_model` must already exist on Replicate as an empty private
    model (create it at replicate.com/create) in the form 'username/model-name'.
    """
    if not os.path.exists(photos_zip_path):
        raise FileNotFoundError(f"Training photos not found: {photos_zip_path}")

    client = Client(api_token=api_token)
    owner, model_name = destination_model.split("/", 1)
    trainer_owner_and_name, trainer_hash = trainer_version.split(":", 1)
    trainer_owner, trainer_name = trainer_owner_and_name.split("/", 1)

    with open(photos_zip_path, "rb") as photos_file:
        training = client.trainings.create(
            model=f"{trainer_owner}/{trainer_name}",
            version=trainer_hash,
            input={
                "input_images": photos_file,
                "trigger_word": trigger_word,
                "steps": training_steps,
                "learning_rate": learning_rate,
                "lora_rank": 16,
                "optimizer": "adamw8bit",
                "batch_size": 1,
                "resolution": "512,768,1024",
                "autocaption": True,
                "caption_dropout_rate": 0.05,
                "cache_latents_to_disk": False,
            },
            destination=f"{owner}/{model_name}",
        )

    logger.info("Training started: %s", training.id)
    return training


def wait_for_training(client: Client, training_id: str, poll_seconds: int = 30):
    """Block until training finishes, printing status as it goes."""
    while True:
        training = client.trainings.get(training_id)
        print(f"[{time.strftime('%H:%M:%S')}] status={training.status}")
        if training.status in {"succeeded", "failed", "canceled"}:
            return training
        time.sleep(poll_seconds)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Train a Flux LoRA on Replicate.")
    parser.add_argument("--photos-zip", required=True,
                        help="Zip of ~20 photos of the subject.")
    parser.add_argument("--destination", required=True,
                        help="Existing empty Replicate model: username/model-name")
    parser.add_argument("--trigger-word", default="TOK")
    parser.add_argument("--steps", type=int, default=1000)
    parser.add_argument("--trainer-version", default=DEFAULT_TRAINER_VERSION,
                        help="Override if Replicate has published a newer trainer.")
    parser.add_argument("--wait", action="store_true",
                        help="Block until training completes.")
    arguments = parser.parse_args()

    api_token = os.environ.get("REPLICATE_API_TOKEN", "").strip()
    if not api_token:
        print("REPLICATE_API_TOKEN is not set.", file=sys.stderr)
        return 1

    training = start_training(
        api_token=api_token,
        photos_zip_path=arguments.photos_zip,
        destination_model=arguments.destination,
        trigger_word=arguments.trigger_word,
        training_steps=arguments.steps,
        trainer_version=arguments.trainer_version,
    )
    print(f"Training id : {training.id}")
    print(f"Follow it at: https://replicate.com/p/{training.id}")

    if arguments.wait:
        client = Client(api_token=api_token)
        finished = wait_for_training(client, training.id)
        if finished.status == "succeeded":
            version_id = (finished.output or {}).get("version", "")
            print("\nTraining succeeded.")
            print(f"Set LORA_MODEL_VERSION={version_id}")
        else:
            print(f"\nTraining {finished.status}: {finished.error}")
            return 1
    else:
        print("\nWhen it finishes, copy the output version id into "
              "LORA_MODEL_VERSION in your .env")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
