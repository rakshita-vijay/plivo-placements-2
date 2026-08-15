"""Stage 1 smoke test: prove the Slack connection works before adding Replicate.

Run this first. If mentioning the bot in a channel produces an in-thread echo,
your tokens, scopes, and Socket Mode setup are all correct, and any later
problem is in the Replicate half.

    python scripts/stage1_echo_bot.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

load_dotenv()


def main() -> int:
    bot_token = os.environ.get("SLACK_BOT_TOKEN", "")
    app_token = os.environ.get("SLACK_APP_TOKEN", "")
    if not bot_token or not app_token:
        print("Set SLACK_BOT_TOKEN and SLACK_APP_TOKEN in .env first.")
        return 1

    app = App(token=bot_token)

    @app.event("app_mention")
    def echo_in_thread(event, say):
        thread_ts = event.get("thread_ts") or event["ts"]
        print(f"Received: {event.get('text')!r} in {event['channel']}/{thread_ts}")
        say(
            text=f":white_check_mark: Stage 1 OK. I heard: _{event.get('text')}_",
            thread_ts=thread_ts,
        )

    @app.event("message")
    def ignore_other_messages(event):
        pass

    print("Stage 1 echo bot connecting. Mention the bot in a channel...")
    SocketModeHandler(app, app_token).start()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
