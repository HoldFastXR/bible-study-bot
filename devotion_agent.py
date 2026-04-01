"""
devotion_agent.py
Generates the daily morning devotion and distributes it.
Cron target: runs once daily at 6:00 AM.

Day-of-week rotation (Mon=0 through Sat=5):
  Mon: Observation focus
  Tue: Key term / original language note
  Wed: Cross-reference thread
  Thu: Redemptive-historical / Christ-centered angle
  Fri: Application to vocational/leadership context
  Sat: Summary + Sunday preparation
"""

import os
import re
import datetime
import json
import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path

from dotenv import load_dotenv
import requests

from gemini_client import generate
from kb_writer import append_to_kb
from system_prompts import DEVOTION_SYSTEM_PROMPT
from state import get_active_passage, set_devotion_sent, devotion_sent_today, load_state, get_devotion_focus

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
GMAIL_ADDRESS = os.getenv("GMAIL_ADDRESS")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")

SUBSCRIBERS_FILE = Path(__file__).parent / "subscribers.json"
LOGS_DIR = Path(__file__).parent / "logs"

DAY_ANGLES = {
    0: ("Observation", "Focus on what the text actually says. Work through the passage verse by verse or in natural units. Identify the key observations — structure, repetition, contrasts, narrative movement. Help the reader slow down and see what is there before interpreting it."),
    1: ("Key Term", "Select one or two key terms or phrases from the passage that are load-bearing for interpretation. Where helpful, note the original Hebrew or Greek. Keep it accessible — transliterate, explain in plain English, show why it matters for understanding the passage."),
    2: ("Cross-Reference", "Trace one or two significant cross-reference threads from the passage. Show how other parts of Scripture illuminate, echo, or develop what this text says. Let Scripture interpret Scripture. Prioritize canonical connections over commentary."),
    3: ("Redemptive-Historical", "Read this passage through the lens of redemptive history. How does it fit in the unfolding story of Scripture? What does it anticipate, fulfill, or extend? Connect it to Christ through promise-fulfillment, typology, or covenantal development — not speculative allegory."),
    4: ("Application", "Focus on application — particularly to leadership, sustained service under pressure, and faith in difficult or complex vocational contexts. Ground the application in the text. Avoid generic moralizing. Connect it specifically to what it means to follow Christ in demanding, high-stakes work."),
    5: ("Weekly Summary", "Bring the week's study together. Briefly synthesize the key observations, interpretive insights, and applications from the passage. Then pivot forward: what should the reader be listening for when they hear this passage preached on Sunday? What question or theme should they carry into worship?"),
}


def get_today_angle() -> tuple[str, str]:
    """Returns (angle_name, angle_instruction) for today's day of week."""
    day = datetime.date.today().weekday()  # 0=Monday, 6=Sunday
    # Default to Observation if it's Sunday (shouldn't run on Sunday)
    return DAY_ANGLES.get(day, DAY_ANGLES[0])


def load_subscribers() -> list[str]:
    if SUBSCRIBERS_FILE.exists():
        with open(SUBSCRIBERS_FILE) as f:
            data = json.load(f)
        return data.get("subscribers", [])
    return []


def generate_devotion(passage: str) -> str:
    angle_name, angle_instruction = get_today_angle()
    today = datetime.date.today()
    day_name = today.strftime("%A")

    focus_override = get_devotion_focus()
    focus_note = f"\nThematic focus for this week (user-specified): {focus_override}\nLet this shape the Application and Prayer sections without overriding the text's own emphasis.\n" if focus_override else ""

    prompt = f"""
Generate a daily Bible devotion for {day_name}, {today.strftime("%B %d, %Y")}.

Passage for the week: {passage}

Today's focus — {angle_name}:
{angle_instruction}
{focus_note}
Format the output with these sections (use markdown bold for headers):
**Scripture** (ESV)
**{angle_name}**
**Application**
**Prayer**

Length: 400–600 words. Substantive but readable in a morning window.
Do not add introductory preamble. Begin directly with the Scripture section.
"""

    return generate(DEVOTION_SYSTEM_PROMPT, prompt, inject_kb_context=True)


def strip_html(text: str) -> str:
    """Remove HTML tags (e.g. <sup>25</sup>) from text."""
    return re.sub(r'<[^>]+>', '', text)


def send_telegram(message: str):
    """Send message to Daniel's Telegram chat."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[devotion] Telegram credentials not set — skipping Telegram send.")
        return

    message = strip_html(message)
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    chunks = [message[i:i+4000] for i in range(0, len(message), 4000)]

    for i, chunk in enumerate(chunks, 1):
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": chunk,
        }
        try:
            resp = requests.post(url, json=payload, timeout=10)
            if resp.ok:
                print(f"[devotion] Telegram sent (chunk {i}/{len(chunks)}).")
            else:
                print(f"[devotion] Telegram send failed (chunk {i}/{len(chunks)}): {resp.status_code} {resp.text[:300]}")
        except Exception as e:
            print(f"[devotion] Telegram send error: {e}")


def send_email_broadcast(subject: str, body: str, subscribers: list[str]):
    """Send devotion to email subscriber list via Gmail SMTP."""
    if not GMAIL_ADDRESS or not GMAIL_APP_PASSWORD:
        print("[devotion] Gmail credentials not set — skipping email broadcast.")
        return

    if not subscribers:
        print("[devotion] No email subscribers — skipping email broadcast.")
        return

    context = ssl.create_default_context()

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context) as server:
            server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)

            for recipient in subscribers:
                msg = MIMEMultipart("alternative")
                msg["Subject"] = subject
                msg["From"] = GMAIL_ADDRESS
                msg["To"] = recipient

                # Plain text version
                part = MIMEText(body, "plain")
                msg.attach(part)

                server.sendmail(GMAIL_ADDRESS, recipient, msg.as_string())
                print(f"[devotion] Email sent to {recipient}")

    except Exception as e:
        print(f"[devotion] Email broadcast error: {e}")


def log_devotion(content: str, passage: str):
    LOGS_DIR.mkdir(exist_ok=True)
    today = datetime.date.today().strftime("%Y-%m-%d")
    log_path = LOGS_DIR / f"devotion_{today}.txt"
    with open(log_path, "w") as f:
        f.write(f"Passage: {passage}\n")
        f.write(f"Generated: {datetime.datetime.utcnow().isoformat()}Z\n")
        f.write("=" * 60 + "\n\n")
        f.write(content)
    print(f"[devotion] Logged to {log_path}")


def write_to_kb(content: str, passage: str):
    """Appends today's devotion to the dated KB capture file."""
    append_to_kb("daily-devo", passage, content)


def run(force: bool = False):
    if not force and devotion_sent_today():
        print("[devotion] Already sent today — skipping.")
        return

    passage = get_active_passage()
    if not passage:
        msg = "⚠️ No active passage set for this week. Text the bot: *This week: [passage reference]*"
        print(f"[devotion] {msg}")
        send_telegram(msg)
        return

    today = datetime.date.today()
    angle_name, _ = get_today_angle()

    print(f"[devotion] Generating {angle_name} devotion for: {passage}")

    try:
        devotion = generate_devotion(passage)
    except ValueError as e:
        if "finish_reason" in str(e) or "reciting" in str(e) or "copyright" in str(e).lower():
            msg = (
                f"⚠️ Devotion for {today.strftime('%A %B %d')} blocked by Gemini content filter "
                f"(copyright/recitation). Passage: {passage}. Manual trigger needed."
            )
            print(f"[devotion] {msg}")
            send_telegram(msg)
            return
        raise

    # Format for Telegram
    header = (
        f"📖 *Morning Devotion — {today.strftime('%A, %B %d')}*\n"
        f"_{passage} | {angle_name}_\n\n"
    )
    telegram_message = header + devotion

    # Format for email (plain text)
    subject = f"Morning Devotion — {today.strftime('%A, %B %d')} | {passage}"
    email_body = f"Morning Devotion — {today.strftime('%A, %B %d, %Y')}\n"
    email_body += f"{passage} | {angle_name}\n"
    email_body += "=" * 50 + "\n\n"
    email_body += devotion
    email_body += "\n\n—\nAlliance Bible Fellowship Boone | Daily Devotion"

    # Send
    send_telegram(telegram_message)
    subscribers = load_subscribers()
    send_email_broadcast(subject, email_body, subscribers)

    # Persist
    log_devotion(devotion, passage)
    write_to_kb(devotion, passage)
    set_devotion_sent(today.strftime("%Y-%m-%d"))

    print("[devotion] Done.")


if __name__ == "__main__":
    run()
