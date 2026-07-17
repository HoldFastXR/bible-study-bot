# Logos HTML Output — Design Notes

House style for every HTML document Logos produces: daily devotions, Phase 1
exegetical studies, Phase 3 journal syntheses, and compiled volumes (e.g.
`~/luke-journal`). The reference implementation is `html_renderer.py` in this
repo; `~/luke-journal/build.py` implements the multi-entry volume variant.
Any new Logos-branded HTML output must follow these notes.

## Palette (CSS custom properties, both themes required)

Dark is the Logos default; light is warm parchment. Wire with
`color-scheme: light dark`, a `prefers-color-scheme: light` media query, and
(for claude.ai artifacts) `[data-theme="dark"]` / `[data-theme="light"]`
overrides on `:root` so the viewer's toggle wins in both directions.

| token      | dark (default) | light      | role                                  |
|------------|----------------|------------|---------------------------------------|
| `--bg-top` | `#181B20`      | `#FBFAF5`  | page gradient top (fixed attachment)   |
| `--bg-bot` | `#101216`      | `#F1EDE2`  | page gradient bottom                   |
| `--text`   | `#E4E3DD`      | `#282420`  | body text                              |
| `--soft`   | `#A6A79F`      | `#6E685B`  | subtitles, em text, meta, attributions |
| `--accent` | `#BC8B6C`      | `#A66B49`  | dusty terracotta — the ONLY accent     |
| `--line`   | `#2B2F37`      | `#E3DCCC`  | hairlines, borders                     |
| `--rule`   | `#3A3F49`      | `#D8CFBB`  | ornamental double rules                |
| `--panel`  | `#1C2026`      | `#F2EDE0`  | scripture/contents cards               |

No second accent color, ever. Semantic emphasis comes from type and spacing.

## Typography

- One family: `Charter, "Iowan Old Style", Georgia, "Times New Roman", serif`
  for everything, including labels. No sans, no mono, no webfonts.
- Body 18px, line-height 1.62, reading column **max-width 680px**, centered.
- Body paragraphs 1.06rem; scripture text 1rem/1.7.
- **Kicker labels** (the signature device): 11px, `letter-spacing:.28em`,
  uppercase, accent color, weight 600. Used for the doc type line
  ("LOGOS · DAILY READING", "LUKE 15:8-10 · SERMON APRIL 26, 2026").
- Section headings render as kicker-style accent labels (12px, `.2em` tracking,
  uppercase) with a trailing hairline: `display:flex` + `::after` line.
- Titles: weight 600, `clamp()` sized (~1.7–2.5rem), `text-wrap: balance`.
- Subtitles italic in `--soft`.

## Signature ornaments (what makes it Logos)

1. **Olive sprig** — the inline SVG in `html_renderer.py` (`SPRIG` large for
   the masthead, `SPRIG_SM` small for entry headers/footers). Always
   `currentColor` on an accent-colored element; never recolor per-instance.
2. **Double rule with fleuron** (`.drule`): two 1px `--rule` lines, max-width
   340px, centered ❧ on `--bg-top` background. Sits under the masthead title.
3. **Fleuron `❧`** in accent, centered, as the horizontal-rule replacement and
   end-of-entry mark.
4. **Scripture card**: `--panel` background, 2px accent left border,
   `0 6px 6px 0` radius, "SCRIPTURE" kicker label, ESV text with bracketed
   verse numbers, then `ESV® · © Crossway` attribution line in `--soft` .7rem.
   Every study document opens with the passage — never the reference alone
   (fetch via `esv_client.py`, cached in `.esv_cache/`).
5. **Drop cap** on the first body paragraph of single-document outputs
   (devotions): 3.4em accent first-letter. Skip in multi-entry volumes where
   bodies open with headed lists.

## Document skeleton

Header (centered): sprig → kicker → title → italic subtitle → drule ❧.
Then scripture card → body → centered footer: small sprig + 11px uppercase
`--soft` line ("Generated/Compiled {date} · Alliance Bible Fellowship, Boone").

Volume variant (luke-journal) adds: contents card (panel, accent left border,
table of passage/title/date/provenance rows), centered chapter dividers
(drule ❧ → "LUKE · CHAPTER 15" kicker → large accent numeral → italic verse
span), and a sticky panel TOC beside the column on ≥900px screens (collapses
to a `<details>` block on mobile).

## Rules of restraint

- Background is always the vertical slate/parchment gradient, fixed attachment.
- Lists get accent `::marker`; `em` renders in `--soft`, not italicized accent.
- No cards/borders around running text — panels are reserved for scripture and
  contents. No shadows. Radius 6px on panels only.
- Wide content scrolls inside its own `overflow-x:auto` container.
- Focus-visible outlines in accent; respect `prefers-reduced-motion`.
