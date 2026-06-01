"""
esv_client.py
Fetches passage text from the Crossway ESV API (api.esv.org), cached on disk.

Why this exists: asking Gemini to reproduce ESV text trips its copyright/recitation
filter (longer passages come back blocked or reference-only). Instead we fetch the
text ourselves and insert it, so devotions and study documents always carry the
real passage.

Requires ESV_API_KEY in the environment (.env). If the key is missing or the call
fails, get_passage_text() returns None and callers fall back to the reference alone.

ESV API terms: non-commercial use; attribution required (see ATTRIBUTION).
"""

import os
import re
from pathlib import Path

import requests

TEXT_ENDPOINT = "https://api.esv.org/v3/passage/text/"
CACHE_DIR = Path(__file__).parent / ".esv_cache"

ATTRIBUTION = (
    "Scripture quotations are from the ESV® Bible (The Holy Bible, English "
    "Standard Version®), © 2001 by Crossway, a publishing ministry of "
    "Good News Publishers. Used by permission. All rights reserved."
)


def _cache_path(passage: str) -> Path:
    slug = re.sub(r"[^a-z0-9]+", "-", passage.lower()).strip("-") or "passage"
    return CACHE_DIR / f"{slug}.txt"


def get_passage_text(passage: str) -> str | None:
    """
    Return clean ESV text for a reference (e.g. "Luke 15:11-24"), or None if
    unavailable (no API key, network error, or empty result). Each passage is
    fetched at most once and then served from the on-disk cache.
    """
    if not passage:
        return None

    cache = _cache_path(passage)
    if cache.exists():
        cached = cache.read_text(encoding="utf-8").strip()
        return cached or None

    api_key = os.getenv("ESV_API_KEY")
    if not api_key:
        return None

    try:
        resp = requests.get(
            TEXT_ENDPOINT,
            params={
                "q": passage,
                "include-headings": "false",
                "include-footnotes": "false",
                "include-verse-numbers": "true",
                "include-short-copyright": "false",
                "include-passage-references": "false",
            },
            headers={"Authorization": f"Token {api_key}"},
            timeout=15,
        )
        resp.raise_for_status()
        passages = resp.json().get("passages", [])
        text = passages[0].strip() if passages else ""
    except Exception as e:
        print(f"[esv_client] fetch failed for {passage!r}: {e}")
        return None

    if not text:
        return None

    CACHE_DIR.mkdir(exist_ok=True)
    cache.write_text(text, encoding="utf-8")
    return text
