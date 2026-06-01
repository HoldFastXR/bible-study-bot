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

Site structure (Wix-hosted, confirmed 2026-05-28):
  - Index at /sermons/ — each sermon is a `div.wixui-repeater__item` card,
    listed newest-first, containing an <h3> title, a "/sermon/<slug>" detail
    link, and a "Month D, YYYY" date line. Empty placeholder cards exist.
  - Title format: "LUKE 16:14-15" — passage is always in the title.
  - Detail page transcript lives in <main>; plain body text, no login required.
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

SERMON_LINK_PATTERN = re.compile(r"/sermon/[^/?#]+$")
SITE_ROOT = "https://www.abfboone.com"


def _absolutize(href: str) -> str:
    return SITE_ROOT + href if href.startswith("/") else href


def _date_from_card(card) -> tuple[str | None, "date | None"]:
    """Find the first 'Month D, YYYY' date string within a listing card."""
    for text in card.stripped_strings:
        parsed = parse_sermon_date(text)
        if parsed:
            return text.strip(), parsed
    return None, None


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
        # Wix detail pages show the date without the legacy "| " prefix —
        # fall back to scanning individual text lines.
        if parsed_date is None:
            for line in soup.stripped_strings:
                parsed_date = parse_sermon_date(line)
                if parsed_date:
                    date_str = line.strip()
                    break

        # Look for a scripture reference in the first 2000 chars of body text
        early_text = page_text[:2000]
        ref_match = SCRIPTURE_REF_PATTERN.search(early_text)
        passage = ref_match.group(1).strip() if ref_match else None

        return {"date_str": date_str, "date": parsed_date, "passage": passage}
    except Exception as e:
        print(f"[sermon_fetcher] Could not fetch metadata from {sermon_url}: {e}")
        return {"date_str": None, "date": None, "passage": None}


def fetch_sermon_index() -> list[dict]:
    """
    Parse the ABF sermons listing (Wix-hosted as of 2026-05).

    Primary path: each sermon is a `div.wixui-repeater__item` card carrying the
    title (<h3>), the "/sermon/<slug>" detail link, and a date line — all in the
    static HTML, newest-first. Empty placeholder cards are skipped.

    If the Wix card markup is absent (future site change), fall back to a generic
    scan that pairs scripture-titled <h3> headings with "/sermon/" links by order.
    """
    response = requests.get(INDEX_URL, timeout=15)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")

    sermons = []
    for card in soup.select("div.wixui-repeater__item"):
        h3 = card.find("h3")
        title = h3.get_text(strip=True) if h3 else ""
        if not title:
            continue

        link = None
        for a in card.find_all("a", href=True):
            if SERMON_LINK_PATTERN.search(a["href"]):
                link = _absolutize(a["href"])
                break
        if not link:
            continue

        date_str, parsed_date = _date_from_card(card)
        passage = extract_passage_from_title(title)

        # Only hit the detail page if the card was missing passage or date.
        if passage is None or parsed_date is None:
            meta = fetch_sermon_metadata(link)
            passage = passage or meta["passage"]
            date_str = date_str or meta["date_str"]
            parsed_date = parsed_date or meta["date"]

        sermons.append({
            "title": title,
            "url": link,
            "date_str": date_str,
            "date": parsed_date,
            "passage": passage,
        })

    if sermons:
        return sermons

    return _fetch_sermon_index_fallback(soup)


def _fetch_sermon_index_fallback(soup) -> list[dict]:
    """Defensive fallback: pair scripture-titled <h3> headings with /sermon/ links."""
    sermon_links, seen = [], set()
    for a in soup.find_all("a", href=True):
        if SERMON_LINK_PATTERN.search(a["href"]) and a["href"] not in seen:
            seen.add(a["href"])
            sermon_links.append(_absolutize(a["href"]))

    titles = [
        t for t in (h3.get_text(strip=True) for h3 in soup.find_all("h3"))
        if extract_passage_from_title(t)
    ]

    sermons = []
    for i, title in enumerate(titles):
        if i >= len(sermon_links):
            break
        meta = fetch_sermon_metadata(sermon_links[i])
        sermons.append({
            "title": title,
            "url": sermon_links[i],
            "date_str": meta["date_str"],
            "date": meta["date"],
            "passage": extract_passage_from_title(title) or meta["passage"],
        })
    return sermons


def detect_passage_from_obsidian() -> str | None:
    """
    Fallback: scan recent Drop Zone processed files and KB bible-study notes
    for a scripture passage reference written within the last 7 days.
    Returns the most-recently-dated passage found, or None.
    """
    from datetime import date, timedelta

    search_dirs = [
        Path.home() / ".chief-of-staff" / "obsidian-repo" / "Drop Zone" / "processed",
        Path.home() / "chief-of-staff" / "knowledge-base" / "personal" / "bible-study",
    ]

    cutoff = date.today() - timedelta(days=7)
    candidates = []

    for search_dir in search_dirs:
        if not search_dir.exists():
            continue
        for md_file in sorted(search_dir.glob("*.md"), reverse=True):
            try:
                mtime = date.fromtimestamp(md_file.stat().st_mtime)
                if mtime < cutoff:
                    continue
                content = md_file.read_text(encoding="utf-8", errors="ignore")
                # Look for scripture references: Book Chapter:Verse or Book Chapter:Verse-Verse
                for match in SCRIPTURE_REF_PATTERN.finditer(content):
                    ref = match.group(1).strip()
                    # Exclude obviously non-scripture refs (short refs like "v3" or single numbers)
                    if re.match(r"[A-Z][a-z]", ref) and ":" in ref:
                        candidates.append((mtime, ref))
            except Exception:
                continue

    if not candidates:
        return None

    # Return the passage from the most recent note
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]


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
        print(f"[sermon_fetcher] Already have sermon from {latest['date_str']}. Checking Obsidian notes for new passage...")
        # Fallback: detect passage from recent Obsidian/KB notes (e.g. user took notes at church)
        obs_passage = detect_passage_from_obsidian()
        current_passage = state.get("active_passage", "")
        if obs_passage and obs_passage != current_passage:
            set_active_passage(obs_passage)
            msg = (
                f"📖 No new sermon on site yet, but detected new passage from your notes: "
                f"*{obs_passage}*\nDevotions will use this passage starting tomorrow."
            )
            print(f"[sermon_fetcher] {msg}")
            if notify_telegram:
                notify_telegram(msg)
            return {"found": False, "reason": "passage_from_notes", "passage": obs_passage}
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

    # ── Step 5: Kick the Logos weekly batch (CC produces Phase 1 + 6 devotions) ──
    # Phase 1 must remain unbiased (no sermon input) — the CC command honours that.
    # Phase 2 + Phase 3 are gated on-command ("write the journal entry").
    if passage:
        word_count = len(transcript.split())
        if notify_telegram:
            notify_telegram(
                f"📖 Sermon loaded for *{passage}* — Pastor Scott Andrews | "
                f"{latest['date_str']} | {word_count:,} words.\n\n"
                f"Kicking the Logos weekly batch (Phase 1 + Mon–Sat devotions). "
                f"I'll let you know when the week is ready."
            )
        try:
            import subprocess
            subprocess.Popen(
                ["/home/daniel/chief-of-staff/run_logos_week.sh", passage],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            print(f"[sermon_fetcher] Logos weekly batch kicked for {passage}.")
        except Exception as e:
            msg = f"⚠️ Could not launch logos-week batch: {e}"
            print(msg)
            if notify_telegram:
                notify_telegram(msg)

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
