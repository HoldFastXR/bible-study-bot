"""
sermon_fetcher.py
Sunday evening automation. Single cron entry does everything:

  1. Scrapes https://www.abfboone.com/luke/ for the latest sermon
  2. Extracts the passage reference from the sermon title (e.g. "LUKE 14:12-24")
  3. Sets it as the active weekly passage in state.json
  4. Fetches and stores the full transcript
  5. Runs Phase 1 exegetical study automatically
  6. Runs Phase 2 sermon analysis automatically
  7. Sends Daniel one Telegram notification:
       "Everything is ready. Say 'write the journal entry' when you're ready for Phase 3."

After this runs, Daniel's only manual step for the weekly study is triggering Phase 3.

Site structure (confirmed by inspection):
  - Index at /luke/ — most recent sermon listed first as h2 > a
  - Title format: "LUKE 14:12-24" or "LUKE 13:31-35" — passage is always in the title
  - Full transcript is plain HTML body text, no login required
"""

import os
import re
import requests
from bs4 import BeautifulSoup
from datetime import datetime, date
from pathlib import Path

from state import (
    set_sermon_fetched,
    set_active_passage,
    set_phase_complete,
    load_state,
)

SERMONS_DIR = Path(__file__).parent / "sermons"
INDEX_URL = "https://www.abfboone.com/sermons/"

MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12
}


# ── Parsing Helpers ───────────────────────────────────────────────────────────

def parse_sermon_date(date_str: str) -> date | None:
    try:
        match = re.match(r"(\w+)\s+(\d+),\s+(\d{4})", date_str.strip())
        if match:
            month_name, day, year = match.groups()
            month = MONTHS.get(month_name.lower())
            if month:
                return date(int(year), month, int(day))
    except Exception:
        pass
    return None


def extract_passage_from_title(title: str) -> str | None:
    """
    Extracts a normalised passage reference from a sermon title.
    "LUKE 14:12-24"        → "Luke 14:12-24"
    "LUKE 13:31-35"        → "Luke 13:31-35"
    "LUKE 12:35-48 (PART 2)" → "Luke 12:35-48"
    Works for any book name in the title.
    """
    # Match: WORD(S) CHAPTER:VERSE[-VERSE] optionally followed by junk
    match = re.match(
        r"([A-Z][A-Z\s]+?)\s+(\d+:\d+(?:-\d+)?)",
        title.strip().upper()
    )
    if match:
        book = match.group(1).strip().title()
        ref = match.group(2)
        return f"{book} {ref}"
    return None


# ── Fetching ──────────────────────────────────────────────────────────────────

DATE_PATTERN = re.compile(
    r"\|\s*((?:January|February|March|April|May|June|July|August|"
    r"September|October|November|December)\s+\d+,\s+\d{4})"
)

SCRIPTURE_REF_PATTERN = re.compile(
    r"\b((?:[123]\s)?[A-Z][a-z]+\s+\d+:\d+(?:-\d+)?)\b"
)


def fetch_sermon_metadata(sermon_url: str) -> dict:
    """
    Fetches an individual sermon page to extract date and passage reference.
    Used when the listing page doesn't carry that metadata.
    Returns {"date_str": ..., "date": ..., "passage": ...} with None values on failure.
    """
    try:
        resp = requests.get(sermon_url, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # Remove nav/header/footer noise
        for tag in soup.find_all(["nav", "header", "footer"]):
            tag.decompose()

        page_text = soup.get_text()

        date_match = DATE_PATTERN.search(page_text)
        date_str = date_match.group(1).strip() if date_match else None
        parsed_date = parse_sermon_date(date_str) if date_str else None

        # Look for a scripture reference in the first 2000 chars of body text
        early_text = page_text[:2000]
        ref_match = SCRIPTURE_REF_PATTERN.search(early_text)
        passage = ref_match.group(1).strip() if ref_match else None

        return {"date_str": date_str, "date": parsed_date, "passage": passage}
    except Exception as e:
        print(f"[sermon_fetcher] Could not fetch metadata from {sermon_url}: {e}")
        return {"date_str": None, "date": None, "passage": None}


def fetch_sermon_index() -> list[dict]:
    response = requests.get(INDEX_URL, timeout=15)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    sermons = []

    for h3 in soup.find_all("h3"):
        a = h3.find("a")
        if not a:
            continue

        title = a.get_text(strip=True)
        url = a.get("href", "")

        if "abfboone.com" not in url:
            continue

        passage = extract_passage_from_title(title)

        # The sermons listing page carries no date metadata — fetch from individual page.
        # Also resolve passage if the title doesn't contain a scripture reference
        # (e.g. "PALM SUNDAY 2026").
        if passage is None:
            meta = fetch_sermon_metadata(url)
            date_str = meta["date_str"]
            parsed_date = meta["date"]
            passage = meta["passage"]
        else:
            # Still need the date — fetch it from the individual page
            meta = fetch_sermon_metadata(url)
            date_str = meta["date_str"]
            parsed_date = meta["date"]

        sermons.append({
            "title": title,
            "url": url,
            "date_str": date_str,
            "date": parsed_date,
            "passage": passage,
        })

    return sermons


def fetch_sermon_transcript(sermon_url: str) -> str:
    response = requests.get(sermon_url, timeout=15)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")

    for tag in soup.find_all(["nav", "header", "footer"]):
        tag.decompose()

    content = (
        soup.find("div", class_="entry-content") or
        soup.find("div", class_="post-content") or
        soup.find("article") or
        soup.find("main")
    )

    if not content:
        paragraphs = soup.find_all("p")
        return "\n\n".join(p.get_text(strip=True) for p in paragraphs if p.get_text(strip=True))

    # Remove Watch/Listen navigation sections
    for h2 in content.find_all("h2"):
        if h2.get_text(strip=True).lower() in ("watch", "listen"):
            next_sib = h2.find_next_sibling()
            if next_sib:
                next_sib.decompose()
            h2.decompose()

    raw = content.get_text(separator="\n", strip=True)
    lines = [line.strip() for line in raw.split("\n")]
    cleaned = []
    blank_count = 0
    for line in lines:
        if not line:
            blank_count += 1
            if blank_count <= 1:
                cleaned.append("")
        else:
            blank_count = 0
            cleaned.append(line)

    return "\n".join(cleaned).strip()


def store_transcript(title: str, sermon_date: date, transcript: str) -> str:
    SERMONS_DIR.mkdir(exist_ok=True)
    filename = f"sermon_{sermon_date.strftime('%Y-%m-%d')}.txt"
    filepath = SERMONS_DIR / filename

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(f"TITLE: {title}\n")
        f.write(f"DATE: {sermon_date.strftime('%B %d, %Y')}\n")
        f.write(f"SOURCE: {INDEX_URL}\n")
        f.write(f"FETCHED: {datetime.utcnow().isoformat()}Z\n")
        f.write("=" * 60 + "\n\n")
        f.write(transcript)

    return str(filepath)


# ── Main Pipeline ─────────────────────────────────────────────────────────────

def run(notify_telegram=None) -> dict:
    """
    Full Sunday evening pipeline:
      fetch → extract passage → set active → run Phase 1 → run Phase 2 → notify

    notify_telegram: optional callable(message: str) for Telegram updates.
    Returns result dict.
    """
    print(f"[sermon_fetcher] Checking {INDEX_URL}...")

    # ── Step 1: Fetch index ───────────────────────────────────────────────────
    try:
        sermons = fetch_sermon_index()
    except Exception as e:
        msg = f"⚠️ Sermon fetcher: failed to load index. Error: {e}"
        print(msg)
        if notify_telegram:
            notify_telegram(msg)
        return {"found": False, "error": str(e)}

    if not sermons:
        msg = "⚠️ Sermon fetcher: no sermons found on index page."
        print(msg)
        if notify_telegram:
            notify_telegram(msg)
        return {"found": False}

    latest = sermons[0]

    # ── Step 2: Check if already fetched this week ────────────────────────────
    state = load_state()
    latest_date_iso = latest["date"].isoformat() if latest["date"] else None
    if state.get("sermon_date") == latest_date_iso:
        print(f"[sermon_fetcher] Already have sermon from {latest['date_str']}. Nothing to do.")
        return {"found": False, "reason": "already_fetched"}

    # ── Step 3: Fetch transcript ──────────────────────────────────────────────
    print(f"[sermon_fetcher] New sermon: {latest['title']} ({latest['date_str']})")
    try:
        transcript = fetch_sermon_transcript(latest["url"])
    except Exception as e:
        msg = f"⚠️ Sermon fetcher: found listing but failed to fetch transcript. Error: {e}"
        print(msg)
        if notify_telegram:
            notify_telegram(msg)
        return {"found": False, "error": str(e)}

    if not transcript or len(transcript) < 200:
        msg = f"⚠️ Sermon fetcher: transcript for {latest['title']} appears too short. Manual check needed."
        print(msg)
        if notify_telegram:
            notify_telegram(msg)
        return {"found": False, "reason": "transcript_too_short"}

    sermon_date = latest["date"] or date.today()
    filepath = store_transcript(latest["title"], sermon_date, transcript)

    # ── Step 4: Set active passage (before set_sermon_fetched so the flag isn't reset) ──
    passage = latest.get("passage")
    if passage:
        set_active_passage(passage)
        print(f"[sermon_fetcher] Active passage set: {passage}")
    else:
        msg = (
            f"⚠️ Could not extract passage from title: \"{latest['title']}\". "
            f"Please set it manually by texting the bot the passage."
        )
        print(msg)
        if notify_telegram:
            notify_telegram(msg)

    set_sermon_fetched(sermon_date.isoformat(), filepath)

    # ── Step 5: Run Phase 1 automatically ────────────────────────────────────
    if passage:
        if notify_telegram:
            notify_telegram(f"📖 Sermon loaded for *{passage}*. Running Phase 1 exegetical study...")

        print(f"[sermon_fetcher] Running Phase 1 for {passage}...")
        try:
            from study_session import run_phase1
            phase1_output = run_phase1()
            print(f"[sermon_fetcher] Phase 1 complete ({len(phase1_output)} chars).")
        except Exception as e:
            msg = f"⚠️ Phase 1 failed: {e}"
            print(msg)
            if notify_telegram:
                notify_telegram(msg)
            return {"found": True, "passage": passage, "error": f"Phase 1 failed: {e}"}

        # ── Step 6: Run Phase 2 automatically ────────────────────────────────
        print(f"[sermon_fetcher] Running Phase 2 sermon analysis...")
        try:
            from study_session import run_phase2
            phase2_output = run_phase2()
            print(f"[sermon_fetcher] Phase 2 complete ({len(phase2_output)} chars).")
        except Exception as e:
            msg = f"⚠️ Phase 2 failed: {e}"
            print(msg)
            if notify_telegram:
                notify_telegram(msg)
            return {"found": True, "passage": passage, "error": f"Phase 2 failed: {e}"}

        # ── Step 7: Final notification ────────────────────────────────────────
        word_count = len(transcript.split())
        summary_msg = (
            f"✅ *Weekly study ready — {passage}*\n\n"
            f"Pastor Scott Andrews | {latest['date_str']}\n"
            f"Sermon: {word_count:,} words\n\n"
            f"Phase 1 exegetical study: complete\n"
            f"Phase 2 sermon analysis: complete\n\n"
            f"When you're ready, just say *\"write the journal entry\"* to run Phase 3."
        )
        print(summary_msg)
        if notify_telegram:
            notify_telegram(summary_msg)

    return {
        "found": True,
        "title": latest["title"],
        "passage": passage,
        "date_str": latest["date_str"],
        "file": filepath,
    }


if __name__ == "__main__":
    result = run()
    print(result)
