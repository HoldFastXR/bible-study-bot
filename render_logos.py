"""
render_logos.py
Renders a Logos batch week (markdown → styled HTML) using html_renderer + esv_client.

CC produces content (markdown) only. This script handles presentation:
  - reads <week_dir>/manifest.json
  - fetches the week's ESV passage text once (cached on disk via esv_client)
  - renders phase1.md, each devo-<day>.md, and phase3.md if present
  - writes the corresponding .html files next to the .md files

Idempotent. Safe to re-run.

Usage:
    python3 render_logos.py [<week_dir>]   # defaults to the current ISO week
"""

import datetime
import json
import sys
from pathlib import Path

from esv_client import get_passage_text
from html_renderer import write_study_html
import logos_io

DAY_NAMES = {
    "mon": ("Monday", "Observation"),
    "tue": ("Tuesday", "Key Term"),
    "wed": ("Wednesday", "Cross-Reference"),
    "thu": ("Thursday", "Redemptive-Historical"),
    "fri": ("Friday", "Application"),
    "sat": ("Saturday", "Weekly Summary"),
}


def _wrap_devo_md(day_long: str, angle: str, passage: str, body_md: str) -> str:
    """Give each devo markdown a small heading so the HTML doc title section makes sense."""
    return f"## {angle}\n\n{body_md.strip()}\n"


def render_week(week_dir: Path) -> dict:
    manifest_path = week_dir / "manifest.json"
    if not manifest_path.exists():
        raise SystemExit(f"no manifest at {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    passage = manifest.get("passage") or "(passage)"
    week_id = manifest.get("week_id") or week_dir.name

    # Single ESV fetch for the week; cached after first call.
    scripture = get_passage_text(passage)
    rendered = []

    def _render(md_path: Path, title: str, subtitle: str, slug: str) -> Path | None:
        if not md_path.exists():
            return None
        body = md_path.read_text(encoding="utf-8")
        # write_study_html writes to ./rendered/<slug>-<stamp>.html — for batch we
        # want deterministic filenames adjacent to the .md, so we'll inline-render
        # and write directly.
        from html_renderer import render_study_html
        html = render_study_html(title, subtitle, body, scripture=scripture)
        out = md_path.with_suffix(".html")
        out.write_text(html, encoding="utf-8")
        return out

    # Phase 1
    p = _render(
        week_dir / "phase1.md",
        title=f"{passage} — Exegetical Study",
        subtitle=f"Phase 1 · Text-first exegesis · Week {week_id}",
        slug=f"{passage}-phase1",
    )
    if p:
        rendered.append(str(p))

    # Devotions
    for key, (day_long, angle) in DAY_NAMES.items():
        md = week_dir / f"devo-{key}.md"
        if not md.exists():
            continue
        # Don't mutate the markdown content; just title the rendered doc.
        p = _render(
            md,
            title=f"{day_long} Devotion — {passage}",
            subtitle=f"{angle} · Week {week_id}",
            slug=f"devo-{key}-{week_id}",
        )
        if p:
            rendered.append(str(p))

    # Phase 3 (only present after /logos-journal)
    p = _render(
        week_dir / "phase3.md",
        title=f"{passage} — Journal Synthesis",
        subtitle=f"Phase 3 · Integrated journal entry · Week {week_id}",
        slug=f"{passage}-phase3",
    )
    if p:
        rendered.append(str(p))

    return {"passage": passage, "week_id": week_id, "rendered": rendered,
            "scripture_loaded": bool(scripture)}


def main(argv: list[str]) -> int:
    if len(argv) > 1:
        week_dir = Path(argv[1]).expanduser().resolve()
    else:
        week_dir = logos_io.week_dir()
    if not week_dir.exists():
        print(f"[render_logos] week dir missing: {week_dir}", file=sys.stderr)
        return 1
    result = render_week(week_dir)
    print(f"[render_logos] {result['passage']} ({result['week_id']}): "
          f"{len(result['rendered'])} file(s) rendered, "
          f"esv={'yes' if result['scripture_loaded'] else 'no'}")
    for r in result["rendered"]:
        print(f"  - {r}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
