"""
html_renderer.py
Renders Logos long-form study output (Phase 1 exegesis, Phase 3 journal synthesis)
to a styled, standalone HTML document for comfortable reading outside Telegram.

The phase outputs are LLM-generated Markdown with a predictable, narrow set of
constructs: ATX headings, **bold** / *italic*, ordered and unordered lists
(with light indentation-based nesting), `---` rules, and plain paragraphs
(including "Observation vs inference:" and "Greek note:" lines). A small,
self-contained converter handles exactly those — no third-party dependency, so
nothing new needs deploying to the server.

Public API:
    render_study_html(title, subtitle, body_markdown) -> str   # full HTML doc
    write_study_html(title, subtitle, body_markdown, slug) -> str  # writes file, returns path
"""

import datetime
import html
import os
import re
from pathlib import Path

from esv_client import ATTRIBUTION as ESV_ATTRIBUTION

RENDERED_DIR = Path(__file__).parent / "rendered"

_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_ITALIC_RE = re.compile(r"(?<!\*)\*(?!\s)(.+?)(?<!\s)\*(?!\*)")
_ORDERED_RE = re.compile(r"^(\s*)(\d+)\.\s+(.*)$")
_UNORDERED_RE = re.compile(r"^(\s*)[-*]\s+(.*)$")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_RULE_RE = re.compile(r"^\s*([-*_])\1{2,}\s*$")


def _inline(text: str) -> str:
    """Escape HTML then apply inline bold/italic formatting."""
    text = html.escape(text, quote=False)
    text = _BOLD_RE.sub(r"<strong>\1</strong>", text)
    text = _ITALIC_RE.sub(r"<em>\1</em>", text)
    return text


def _indent_level(spaces: str) -> int:
    """Map leading whitespace to a nesting level (every 2 spaces = one level)."""
    return len(spaces.expandtabs(4)) // 2


def markdown_to_html_fragment(md: str) -> str:
    """Convert the supported Markdown subset to an HTML body fragment."""
    lines = md.replace("\r\n", "\n").split("\n")
    out: list[str] = []
    # list_stack holds tuples of (tag, level) for currently-open lists.
    list_stack: list[tuple[str, int]] = []
    para: list[str] = []

    def flush_para():
        if para:
            out.append("<p>" + _inline(" ".join(para).strip()) + "</p>")
            para.clear()

    def close_lists_to(level: int):
        while list_stack and list_stack[-1][1] >= level:
            tag, _ = list_stack.pop()
            out.append(f"</{tag}>")

    def close_all_lists():
        while list_stack:
            tag, _ = list_stack.pop()
            out.append(f"</{tag}>")

    for raw in lines:
        line = raw.rstrip()

        if not line.strip():
            flush_para()
            continue

        if _RULE_RE.match(line):
            flush_para()
            close_all_lists()
            out.append("<hr/>")
            continue

        heading = _HEADING_RE.match(line)
        if heading:
            flush_para()
            close_all_lists()
            hashes = len(heading.group(1))
            # Doc already carries an <h1>; collapse #/## -> h2, ### -> h3, #### -> h4.
            level = 2 if hashes <= 2 else min(hashes, 6)
            out.append(f"<h{level}>{_inline(heading.group(2).strip())}</h{level}>")
            continue

        ordered = _ORDERED_RE.match(line)
        unordered = None if ordered else _UNORDERED_RE.match(line)
        if ordered or unordered:
            flush_para()
            if ordered:
                indent, content, tag = ordered.group(1), ordered.group(3), "ol"
            else:
                indent, content, tag = unordered.group(1), unordered.group(2), "ul"
            level = _indent_level(indent)

            close_lists_to(level + 1)
            if not list_stack or list_stack[-1][1] < level:
                out.append(f"<{tag}>")
                list_stack.append((tag, level))
            elif list_stack[-1][0] != tag and list_stack[-1][1] == level:
                # same level, different list type — swap
                closed, _ = list_stack.pop()
                out.append(f"</{closed}>")
                out.append(f"<{tag}>")
                list_stack.append((tag, level))

            out.append(f"<li>{_inline(content.strip())}</li>")
            continue

        # Plain text line — accumulate into a paragraph.
        if list_stack:
            # A non-list, non-blank line ends any open lists.
            close_all_lists()
        para.append(line.strip())

    flush_para()
    close_all_lists()
    return "\n".join(out)


_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{title}</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{
    font-family: Charter, Georgia, "Times New Roman", serif;
    line-height: 1.6; font-size: 18px; color: #1a1a1a;
    background: #fbfbf8; margin: 0; padding: 2rem 1.25rem 4rem;
  }}
  .wrap {{ max-width: 720px; margin: 0 auto; }}
  header.doc {{ border-bottom: 2px solid #d8d2c4; padding-bottom: 1rem; margin-bottom: 2rem; }}
  header.doc .kicker {{ font-size: 0.8rem; letter-spacing: 0.08em; text-transform: uppercase;
    color: #8a7f66; margin: 0 0 0.4rem; }}
  header.doc h1 {{ font-size: 1.7rem; line-height: 1.25; margin: 0 0 0.3rem; }}
  header.doc .sub {{ color: #5c5645; font-style: italic; margin: 0; }}
  h2 {{ font-size: 1.35rem; margin: 2.2rem 0 0.6rem; padding-bottom: 0.25rem;
    border-bottom: 1px solid #e6e0d2; }}
  h3 {{ font-size: 1.12rem; margin: 1.6rem 0 0.4rem; color: #2a2a2a; }}
  h4 {{ font-size: 1rem; margin: 1.2rem 0 0.3rem; color: #4a4a4a; }}
  p {{ margin: 0.7rem 0; }}
  ul, ol {{ margin: 0.6rem 0; padding-left: 1.5rem; }}
  li {{ margin: 0.3rem 0; }}
  section.scripture {{ background: #f3efe3; border-left: 3px solid #c9bd9c;
    padding: 1rem 1.25rem; margin: 0 0 2rem; border-radius: 4px; }}
  section.scripture .passage {{ font-size: 0.97rem; line-height: 1.7; }}
  section.scripture .attribution {{ font-size: 0.72rem; color: #8a7f66;
    margin: 0.9rem 0 0; }}
  hr {{ border: none; border-top: 1px solid #e0dacc; margin: 2rem 0; }}
  strong {{ color: #111; }}
  em {{ color: #3a3a3a; }}
  footer.doc {{ margin-top: 3rem; padding-top: 1rem; border-top: 1px solid #e6e0d2;
    font-size: 0.8rem; color: #9a917c; }}
  @media (prefers-color-scheme: dark) {{
    body {{ background: #15140f; color: #e6e2d6; }}
    header.doc .kicker {{ color: #b3a988; }}
    header.doc .sub {{ color: #b8b29c; }}
    h2 {{ border-color: #33301f; }}
    h3 {{ color: #ece8db; }}
    strong {{ color: #fff; }}
    section.scripture {{ background: #1f1d14; border-left-color: #4a4327; }}
  }}
</style>
</head>
<body>
<div class="wrap">
<header class="doc">
  <p class="kicker">Logos · Bible Study</p>
  <h1>{title}</h1>
  <p class="sub">{subtitle}</p>
</header>
{scripture}
{body}
<footer class="doc">Generated {generated} · Alliance Bible Fellowship, Boone</footer>
</div>
</body>
</html>
"""


def _scripture_section(scripture: str | None) -> str:
    """Render an optional ESV passage block (shown above the study body)."""
    if not scripture:
        return ""
    safe = html.escape(scripture, quote=False).replace("\n", "<br/>\n")
    return (
        '<section class="scripture">\n'
        f'  <div class="passage">{safe}</div>\n'
        f'  <p class="attribution">{html.escape(ESV_ATTRIBUTION, quote=False)}</p>\n'
        "</section>"
    )


def render_study_html(title: str, subtitle: str, body_markdown: str,
                      scripture: str | None = None) -> str:
    """Return a full standalone HTML document for a study/journal output."""
    return _TEMPLATE.format(
        title=html.escape(title, quote=False),
        subtitle=html.escape(subtitle, quote=False),
        scripture=_scripture_section(scripture),
        body=markdown_to_html_fragment(body_markdown),
        generated=datetime.datetime.now().strftime("%B %d, %Y %H:%M"),
    )


def write_study_html(title: str, subtitle: str, body_markdown: str, slug: str,
                     scripture: str | None = None) -> str:
    """Render and write the HTML doc to rendered/, returning the file path."""
    RENDERED_DIR.mkdir(exist_ok=True)
    safe_slug = re.sub(r"[^a-z0-9]+", "-", slug.lower()).strip("-") or "study"
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    path = RENDERED_DIR / f"{safe_slug}-{stamp}.html"
    path.write_text(
        render_study_html(title, subtitle, body_markdown, scripture), encoding="utf-8"
    )
    return str(path)
