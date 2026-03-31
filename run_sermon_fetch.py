#!/usr/bin/env python3
"""
run_sermon_fetch.py
Sunday evening cron entry point.

Runs the full pipeline:
  fetch → extract passage → set active → Phase 1 → Phase 2 → notify

Two cron entries — first attempt at 6 PM, retry at 8 PM if sermon not yet posted.
The retry is safe: if already fetched, it exits immediately with no duplicate work.

Crontab entries (add with: crontab -e):
  0 18 * * 0 cd /home/daniel/bible-study-bot && python run_sermon_fetch.py >> logs/cron.log 2>&1
  0 20 * * 0 cd /home/daniel/bible-study-bot && python run_sermon_fetch.py >> logs/cron.log 2>&1
"""

import sys
import os
import requests
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


def notify(message: str):
    """Send Telegram notification."""
    print(f"[{datetime.now().strftime('%H:%M')}] {message}")
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        requests.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "Markdown"
        }, timeout=10)
    except Exception as e:
        print(f"Telegram notify failed: {e}")


def notify_retry():
    """Called at 8 PM if 6 PM attempt found nothing."""
    notify(
        "⏳ No new sermon found yet at 6 PM. Retrying now...\n"
        "If nothing is posted by tonight, check the site manually tomorrow."
    )


if __name__ == "__main__":
    from sermon_fetcher import run
    from state import load_state

    # Check if this is a retry (sermon not found at 6 PM)
    current_hour = datetime.now().hour
    if current_hour >= 19:
        # This is the 8 PM retry run — send a brief notice before trying
        state = load_state()
        if not state.get("sermon_fetched"):
            notify_retry()

    result = run(notify_telegram=notify)

    if result.get("reason") == "already_fetched":
        print("Sermon already fetched this week — nothing to do.")
    elif not result.get("found"):
        # Sermon not posted yet — notify only on the 8 PM run to avoid duplicate messages
        if current_hour >= 19:
            notify(
                "⚠️ No new sermon found after two attempts.\n"
                "The site may not have posted it yet. "
                "Once it's up, just say *\"fetch the sermon\"* and I'll run the full pipeline."
            )
