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

from esv_client import SHORT_ATTRIBUTION as ESV_ATTRIBUTION

RENDERED_DIR = Path(__file__).parent / "rendered"

# Illuminated olive-sprig line art (inherits the accent via currentColor).
SPRIG = (
    '<svg class="sprig" width="132" height="34" viewBox="0 0 132 34" fill="none" aria-hidden="true">'
    '<path d="M66 31 C66 22 66 14 66 6" stroke="currentColor" stroke-width="1.1" stroke-linecap="round"/>'
    '<path d="M66 9 C58 7 52 9 48 4 C55 3 62 5 66 9Z" fill="currentColor" opacity=".85"/>'
    '<path d="M66 9 C74 7 80 9 84 4 C77 3 70 5 66 9Z" fill="currentColor" opacity=".85"/>'
    '<path d="M66 16 C57 15 50 17 45 12 C53 10 61 12 66 16Z" fill="currentColor" opacity=".7"/>'
    '<path d="M66 16 C75 15 82 17 87 12 C79 10 71 12 66 16Z" fill="currentColor" opacity=".7"/>'
    '<path d="M66 23 C59 22 53 24 49 20 C56 18 62 20 66 23Z" fill="currentColor" opacity=".55"/>'
    '<path d="M66 23 C73 22 79 24 83 20 C76 18 70 20 66 23Z" fill="currentColor" opacity=".55"/>'
    '<circle cx="66" cy="4" r="2.1" fill="currentColor"/>'
    '<path d="M30 24 C40 22 48 24 54 27" stroke="currentColor" stroke-width=".8" opacity=".5" stroke-linecap="round"/>'
    '<path d="M102 24 C92 22 84 24 78 27" stroke="currentColor" stroke-width=".8" opacity=".5" stroke-linecap="round"/>'
    "</svg>"
)
SPRIG_SM = (
    '<svg class="sprig" width="70" height="16" viewBox="0 0 70 16" fill="none" aria-hidden="true">'
    '<path d="M35 14 C35 9 35 5 35 2" stroke="currentColor" stroke-width=".9" stroke-linecap="round"/>'
    '<path d="M35 5 C30 4 26 5 23 2 C28 1 33 3 35 5Z" fill="currentColor" opacity=".8"/>'
    '<path d="M35 5 C40 4 44 5 47 2 C42 1 37 3 35 5Z" fill="currentColor" opacity=".8"/>'
    "</svg>"
)

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
            out.append('<p class="fleuron">❧</p>')
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
  :root {{
    color-scheme: light dark;
    /* dark (default) — cool slate, dusty-terracotta accent */
    --bg-top:#181B20; --bg-bot:#101216;
    --text:#E4E3DD; --soft:#A6A79F;
    --accent:#BC8B6C; --line:#2B2F37; --rule:#3A3F49; --panel:#1C2026;
  }}
  @media (prefers-color-scheme: light) {{
    :root {{
      /* light — warm parchment, deeper terracotta for contrast */
      --bg-top:#FBFAF5; --bg-bot:#F1EDE2;
      --text:#282420; --soft:#6E685B;
      --accent:#A66B49; --line:#E3DCCC; --rule:#D8CFBB; --panel:#F2EDE0;
    }}
  }}
  * {{ box-sizing:border-box; margin:0; padding:0; }}
  body {{
    background: linear-gradient(180deg,var(--bg-top),var(--bg-bot)) no-repeat;
    background-attachment: fixed; min-height:100vh;
    color: var(--text);
    font-family: Charter,"Iowan Old Style",Georgia,"Times New Roman",serif;
    line-height:1.62; font-size:18px;
    padding: 32px 16px 72px; -webkit-text-size-adjust:100%;
  }}
  .wrap {{ max-width: 680px; margin:0 auto; }}
  .sprig {{ color:var(--accent); display:block; margin:0 auto 12px; }}
  header.doc {{ text-align:center; margin-bottom: 28px; }}
  header.doc .kicker {{ font-size:11px; letter-spacing:.28em; text-transform:uppercase; color:var(--accent); font-weight:600; }}
  header.doc h1 {{ font-weight:600; font-size:clamp(1.7rem,6vw,2.1rem); line-height:1.15; margin:10px 0 4px; letter-spacing:.005em; }}
  header.doc .sub {{ font-style:italic; color:var(--soft); font-size:1rem; }}
  .drule {{ position:relative; height:10px; margin:20px auto 0; max-width:340px; }}
  .drule::before,.drule::after {{ content:""; position:absolute; left:0; right:0; border-top:1px solid var(--rule); }}
  .drule::before {{ top:3px; }} .drule::after {{ top:6px; }}
  .drule span {{ position:absolute; top:0; left:50%; transform:translateX(-50%); background:var(--bg-top); padding:0 12px; color:var(--accent); font-size:12px; }}

  section.scripture {{ background:var(--panel); border-left:2px solid var(--accent); border-radius:0 6px 6px 0; padding:16px 20px 14px; margin:0 0 30px; }}
  section.scripture .lbl {{ font-size:10.5px; letter-spacing:.2em; text-transform:uppercase; color:var(--accent); font-weight:600; display:block; margin-bottom:9px; }}
  section.scripture .passage {{ font-size:1rem; line-height:1.7; }}
  section.scripture .attribution {{ font-size:.7rem; color:var(--soft); margin:.85rem 0 0; }}

  .doc-body h2 {{ font-size:12px; letter-spacing:.2em; text-transform:uppercase; color:var(--accent); font-weight:600; margin:30px 0 8px; display:flex; align-items:center; gap:10px; }}
  .doc-body h2::after {{ content:""; flex:1; border-top:1px solid var(--line); }}
  .doc-body h3 {{ font-size:1.15rem; font-weight:600; margin:24px 0 6px; }}
  .doc-body h4 {{ font-size:1rem; font-weight:600; color:var(--soft); margin:18px 0 4px; }}
  .doc-body p {{ font-size:1.06rem; margin:0 0 1.05em; }}
  .doc-body ul,.doc-body ol {{ margin:.5rem 0 1rem 1.4rem; }}
  .doc-body li {{ margin:.35rem 0; }}
  .doc-body strong {{ font-weight:700; }}
  .doc-body em {{ color:var(--soft); }}
  .doc-body > p:first-of-type::first-letter {{ font-size:3.4em; line-height:.82; float:left; padding:6px 10px 0 0; color:var(--accent); font-family:Georgia,"Times New Roman",serif; font-weight:600; }}
  p.fleuron {{ text-align:center; color:var(--accent); font-size:20px; margin:30px 0; letter-spacing:.3em; }}

  footer.doc {{ text-align:center; margin-top:36px; padding-top:18px; border-top:1px solid var(--line); }}
  footer.doc .sprig {{ margin-bottom:8px; }}
  footer.doc p {{ font-size:11px; letter-spacing:.12em; text-transform:uppercase; color:var(--soft); }}
</style>
</head>
<body>
<div class="wrap">
<header class="doc">
  {sprig}
  <p class="kicker">Logos · Daily Reading</p>
  <h1>{title}</h1>
  <p class="sub">{subtitle}</p>
  <div class="drule"><span>❧</span></div>
</header>
{scripture}
<div class="doc-body">
{body}
</div>
<footer class="doc">
  {sprig_sm}
  <p>Generated {generated} · Alliance Bible Fellowship, Boone</p>
</footer>
</div>
</body>
</html>
"""


def _scripture_section(scripture: str | None) -> str:
    """Render an optional ESV passage block (the illuminated scripture card)."""
    if not scripture:
        return ""
    safe = html.escape(scripture, quote=False).replace("\n", "<br/>\n")
    return (
        '<section class="scripture">\n'
        '  <span class="lbl">Scripture</span>\n'
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
        sprig=SPRIG,
        sprig_sm=SPRIG_SM,
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
