"""
kb_writer.py
Shared utility for writing Logos-generated content to the Kairos knowledge base.

One-way flow: Logos appends content here → Kairos indexer picks it up on next
enrichment run → content becomes searchable via ChromaDB.

Target directory: ~/chief-of-staff/knowledge-base/personal/bible-study/
Format: {YYYY-MM-DD}.md — one file per day, multiple entries separated by ---
Each entry includes type, passage, timestamp, and full generated text.
"""

import datetime
import os

KB_DIR = os.path.expanduser("~/chief-of-staff/knowledge-base/personal/bible-study")


def append_to_kb(content_type: str, passage: str, content: str) -> str:
    """
    Appends a content entry to today's dated file in the Kairos KB.

    Args:
        content_type: One of 'daily-devo', 'exegetical-phase-1',
                      'exegetical-phase-2', 'journal-synthesis',
                      or 'side-study-synthesis'
        passage:      Scripture reference covered (e.g. "Mark 15:1-15")
        content:      The full generated text to persist

    Returns:
        Absolute path to the file written.
    """
    os.makedirs(KB_DIR, exist_ok=True)

    today = datetime.date.today()
    timestamp = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    filepath = os.path.join(KB_DIR, f"{today.strftime('%Y-%m-%d')}.md")

    # Each entry is separated by \n---\n so the Kairos indexer (chunked=True)
    # produces one ChromaDB chunk per entry.  The header line embeds type,
    # passage, and timestamp directly in the searchable text.
    entry = (
        f"\n\n---\n\n"
        f"## {content_type} | {passage} | {timestamp}\n\n"
        f"{content.strip()}\n"
    )

    with open(filepath, "a", encoding="utf-8") as f:
        f.write(entry)

    print(f"[kb_writer] Appended {content_type} ({passage}) → {filepath}")
    return filepath
