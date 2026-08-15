"""Down Memory Lane — Slack bot entrypoint.

Run with:  python main.py
Socket Mode means no public URL, no ngrok, no inbound firewall rule.
"""

import logging
import signal
import sys

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from slack_bolt.error import BoltError

from config.settings import MissingConfigurationError, load_settings
from replicate_client.inference import FluxLoraInferenceClient
from slack_app.handlers import register_handlers
from slack_app.photo_request_worker import PhotoRequestWorker
from store.job_store import JobStore

logger = logging.getLogger("memory_lane")


def configure_logging(log_level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("slack_bolt").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def build_application():
    settings = load_settings()
    configure_logging(settings.log_level)

    job_store = JobStore(settings.database_path)

    slack_app = App(token=settings.slack_bot_token)

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

    worker = PhotoRequestWorker(
        slack_web_client=slack_app.client,
        inference_client=inference_client,
        job_store=job_store,
        worker_thread_count=settings.worker_thread_count,
    )

    register_handlers(
        app=slack_app,
        job_store=job_store,
        worker=worker,
        trigger_word=settings.lora_trigger_word,
    )

    return settings, slack_app, worker


def main() -> int:
    try:
        settings, slack_app, worker = build_application()
    except MissingConfigurationError as error:
        print(f"Configuration error: {error}", file=sys.stderr)
        return 1
    except BoltError as error:
        # Bolt verifies SLACK_BOT_TOKEN with auth.test during App() construction.
        print(
            f"Slack rejected the bot token: {error}\n"
            f"Check SLACK_BOT_TOKEN (it should start with 'xoxb-') and that the "
            f"app is installed to your workspace.",
            file=sys.stderr,
        )
        return 1

    socket_mode_handler = SocketModeHandler(slack_app, settings.slack_app_token)

    def shut_down(signal_number, _frame):
        logger.info("Signal %s received, shutting down.", signal_number)
        worker.shutdown()
        socket_mode_handler.close()
        sys.exit(0)

    signal.signal(signal.SIGINT, shut_down)
    signal.signal(signal.SIGTERM, shut_down)

    logger.info("Down Memory Lane is connecting to Slack (Socket Mode)...")
    logger.info("LoRA version: %s", settings.lora_model_version[:16] + "...")
    logger.info("Trigger word: %s", settings.lora_trigger_word)
    socket_mode_handler.start()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
