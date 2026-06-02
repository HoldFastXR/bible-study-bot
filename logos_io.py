"""
logos_io.py
Serving-side reader for the Logos batch handoff contract.

Contract (per docs/cc-briefs/SESSION_AC_BRIEF.md):
    ~/chief-of-staff/state/logos/<YYYY-Www>/
        manifest.json
        phase1.md / phase1.html
        devo-mon.md / devo-mon.html  …  devo-sat.{md,html}
        phase2.md / phase3.md / phase3.html       (added by /logos-journal)

The bot reads from this directory by absolute path. Pure read; never mutates.
"""

import datetime
import json
import os
from pathlib import Path

LOGOS_ROOT = Path(os.path.expanduser("~/chief-of-staff/state/logos"))
DAY_KEYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def week_id(d: datetime.date | None = None) -> str:
    """ISO year-week id, matching `date +%G-W%V` used by the run scripts."""
    d = d or datetime.date.today()
    iso_year, iso_week, _ = d.isocalendar()
    return f"{iso_year}-W{iso_week:02d}"


def week_dir(d: datetime.date | None = None) -> Path:
    return LOGOS_ROOT / week_id(d)


def load_manifest(d: datetime.date | None = None) -> dict | None:
    path = week_dir(d) / "manifest.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def devo_path(day_idx: int, fmt: str = "html", d: datetime.date | None = None) -> Path:
    """day_idx: 0=Mon..6=Sun. Returns the path (may not exist)."""
    key = DAY_KEYS[day_idx % 7]
    return week_dir(d) / f"devo-{key}.{fmt}"


def phase_path(phase: str, fmt: str = "html", d: datetime.date | None = None) -> Path:
    """phase: 'phase1' | 'phase2' | 'phase3'."""
    return week_dir(d) / f"{phase}.{fmt}"


def manifest_passage(d: datetime.date | None = None) -> str | None:
    m = load_manifest(d)
    return m.get("passage") if m else None


def passage_matches(active: str | None, d: datetime.date | None = None) -> bool:
    """True when the batch on disk was generated for the current active passage."""
    if not active:
        return False
    mp = manifest_passage(d)
    return bool(mp) and mp.strip().lower() == active.strip().lower()


def has_devo_for_today(d: datetime.date | None = None) -> bool:
    today = d or datetime.date.today()
    return devo_path(today.weekday(), "html", today).exists() or \
           devo_path(today.weekday(), "md", today).exists()


def read_devo_md_for_today(d: datetime.date | None = None) -> str | None:
    today = d or datetime.date.today()
    p = devo_path(today.weekday(), "md", today)
    return p.read_text(encoding="utf-8") if p.exists() else None


def read_phase_md(phase: str, d: datetime.date | None = None) -> str | None:
    p = phase_path(phase, "md", d)
    return p.read_text(encoding="utf-8") if p.exists() else None
