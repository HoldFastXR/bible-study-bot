# Session Summary — March 30, 2026

## Issues Investigated

### 1. Monday devotion not received
The 6:00 AM cron ran successfully and the devotion was generated and logged. The Telegram send
failed silently. Root cause: `send_telegram()` used `parse_mode: "Markdown"`, which Telegram's
parser rejects when content contains `*   **Verse N:**` bullet patterns (returns HTTP 400).
The code caught only connection exceptions, not API-level errors, so the failure was invisible.

### 2. Thursday March 26 devotion missing
Gemini returned `finish_reason: 4` (copyright block — triggered by ESV scripture quotation).
The resulting `ValueError` was unhandled, crashing the script before the Telegram send.

### 3. Sunday sermon pipeline skipped March 29 (Palm Sunday)
Not a bug. The church hadn't posted the March 29 sermon by 6 PM or 8 PM Sunday. Both cron
attempts correctly detected no new sermon and exited. The real underlying bug was that the
fetcher was only checking `https://www.abfboone.com/luke/` — a series-specific page that would
never carry special sermons like Palm Sunday.

### 4. "Give me today's devotion" did nothing
The `DEVOTION` intent handler in `bot.py` called `run_devotion()`, which opens with a
`devotion_sent_today()` guard designed for the cron. Manual requests were silently blocked
with no response to the user.

---

## Fixes Applied

### `devotion_agent.py`
- **Removed `parse_mode: "Markdown"`** from `send_telegram()` — plain text is always reliable.
- **Added response checking** — `resp.ok` is now checked; failures log HTTP status + body.
- **Added success logging** — each sent chunk now logs `[devotion] Telegram sent (chunk N/M)`.
- **Gemini copyright handling** — wrapped `generate_devotion()` in try/except for `ValueError`;
  on a copyright block, sends a warning to Telegram instead of crashing silently.
- **`force` parameter on `run()`** — `run(force=True)` bypasses the `devotion_sent_today()`
  guard, allowing manual triggers after the cron has already fired.

### `sermon_fetcher.py`
- **`INDEX_URL`** changed from `https://www.abfboone.com/luke/` to
  `https://www.abfboone.com/sermons/` — catches all sermons including special/series breaks.
- **Listing scan** changed from `h2` to `h3` (the sermons page structure).
- **URL filter** changed from `startswith(".../luke")` to `"abfboone.com" in url`.
- **`fetch_sermon_metadata(url)`** added — fetches date and passage reference from individual
  sermon pages, needed because the sermons listing carries no dates and some titles
  (e.g. "PALM SUNDAY 2026") contain no scripture reference.
- **`SCRIPTURE_REF_PATTERN`** regex tightened — removed optional second-word group that was
  matching "Read Mark" as a two-word book name.

### `bot.py`
- **`DEVOTION` handler** now calls `run_devotion(force=True)` so manual requests always
  generate and send, regardless of cron state.

---

## State After Session
- Active passage: **Mark 15:1-15** (Palm Sunday 2026, March 29)
- Phase 1 and Phase 2 complete for Mark 15:1-15
- Monday March 30 devotion manually resent (Observation focus)
- Bot restarted via `sudo systemctl restart bible-study-bot` (requires sudo)

---

# Session Summary — March 31, 2026

## Work Done

### GitHub Repository Created
- Installed `gh` CLI v2.45.0 to `/usr/local/bin/gh`, authenticated as `HoldFastXR`
- Initialized git repo at `/home/daniel/bible-study-bot`
- Created `.gitignore` (excludes `.env`, `__pycache__/`, `logs/`, `sermons/`, `state.json`, `.claude/`)
- Pushed 17 source files to **https://github.com/HoldFastXR/bible-study-bot** (public)
- Secrets excluded — `.env` never committed

## State After Session
- Active passage: **Mark 15:1-15** (Phase 2 complete, awaiting Phase 3)
- GitHub repo live and up to date with all source files
- **Action needed:** Rotate API keys (Telegram, Gemini, Anthropic) — keys were read during session exploration and should be considered exposed

---

# Session Summary — April 1, 2026

## Issues Investigated

### 1. Wednesday April 1 devotion blocked by Gemini content filter
Gemini blocked the Mark 15:1–15 devotion with a copyright/recitation error (same root cause as
the March 26 block). The `DEVOTION_SYSTEM_PROMPT` instructed Gemini to output the full passage
text in ESV, which is a copyrighted translation. Longer passages (15+ verses) reliably trip
Gemini's filter; shorter passages had been slipping through, masking the structural problem.

## Theological and Quality Audit

A full prompt-architecture audit was run via CC agent (no log files were available — `logs/`
was gitignored; this has now been corrected). Key findings:

1. **Friday Application angle was a structural moralism trap** — `DAY_ANGLES[4]` pre-loaded a
   vocational landing zone ("leadership, high-stakes work") that overrides textual derivation.
   For a passage like Mark 15:1–15, this produces Pilate-as-cautionary-leadership-tale rather
   than substitutionary Christology. Explicitly prohibited by `CHARTER_BASE` but built into the
   angle instruction.
2. **Model routing was inverted** — The primary user-facing product (daily devotion) was running
   on Gemini free tier; Phase 3 synthesis (triggered once/week) was on Claude Sonnet. This also
   caused the ESV copyright blocks.
3. **Application section equally weighted all days** — No constraint on Application section
   length for non-Application days, causing Mon/Thu to read like Friday.
4. **Tuesday Key Term lacked selection criteria** — Would select high-frequency theological
   vocabulary rather than structurally load-bearing terms.
5. **Wednesday Cross-Reference defaulted to NT-NT** — No instruction to prioritize OT typological
   threads.
6. **Saturday Summary was architecturally stateless** — Could not synthesize the week because
   `generate_devotion()` had no access to Mon–Fri outputs.
7. **Prayer section was angle-agnostic** — Same posture instruction every day regardless of angle.

## Fixes Applied

### `gemini_client.py`
- **`ANTHROPIC_MODEL`** updated from `claude-sonnet-4-5` to `claude-sonnet-4-6` (latest Sonnet)
- **Routing comment** updated to reflect devotions now route to Claude Sonnet

### `devotion_agent.py`
- **`generate_devotion()`** now calls `generate(..., use_claude=True)` — devotions route to
  Claude Sonnet, eliminating ESV copyright blocks and improving theological depth
- **`DAY_ANGLES[1]` (Key Term)** rewritten — added selection criteria: prefer load-bearing terms,
  terms with intertextual freight, terms where English translations diverge; avoid selecting
  terms simply because they are well-known theological words
- **`DAY_ANGLES[2]` (Cross-Reference)** rewritten — added OT priority: typological patterns,
  covenant echoes, prophetic fulfillments; NT-NT cross-references valid but secondary
- **`DAY_ANGLES[4]` (Application)** rewritten — text-first derivation now leads; vocational
  context is a landing zone, not a predetermined destination; explicitly permits worship/
  repentance/comfort applications when the text's movement is Christological or doxological
- **`load_week_devotions()`** added — reads Mon–Fri log files for the current week; Saturday
  Summary prompt now receives actual prior outputs to synthesize rather than generating fresh
- **`SET_DEVOTION_FOCUS` / `CLEAR_DEVOTION_FOCUS` intents** added (prior session, April 1 AM) —
  user can set a thematic focus via Telegram that shapes Application and Prayer sections

### `system_prompts.py`
- **Scripture section** changed from `[Full passage text]` to `[Quote only 1–3 relevant verses]`
  (prior fix, April 1 AM)
- **Application section** now specifies 2–3 sentence maximum on non-Application days
  (Observation, Key Term, Cross-Reference, Redemptive-Historical)
- **Prayer section** now specifies per-angle posture: Observation → attentiveness;
  Key Term → understanding; Cross-Reference → gratitude for Scripture's unity;
  Redemptive-Historical → doxology; Application → petition/consecration; Summary → Sunday prep

### `bot.py`
- `SET_DEVOTION_FOCUS` and `CLEAR_DEVOTION_FOCUS` intents added to classifier and handlers
- `/help` text updated to include devotion focus commands

### `state.py`
- `devotion_focus` field added to state schema with `get_devotion_focus()` / `set_devotion_focus()` helpers

### `.gitignore`
- **`logs/` removed from gitignore** — devotion log files are now committed so future audits
  can evaluate actual output quality rather than prompt architecture alone

## Next Audit
Schedule a theological and quality review after a full week of output (next Wednesday or
Saturday). The Saturday devotion will be the first real test of the log-threading feature.
Key things to evaluate in the next audit:
- Does the Friday Application angle now derive from the text before landing on vocational context?
- Are the day-angle outputs substantively differentiated across the week?
- Is Claude Sonnet producing meaningfully more precise redemptive-historical reasoning?
- Does Saturday's summary actually reflect the week's study?

## State After Session
- Active passage: **Mark 15:1-15** (Wednesday April 1 devotion blocked — manual trigger needed)
- All prompt architecture changes applied and pushed to `claude/fix-devotion-filtering-alhqr`
- Devotions now route to Claude Sonnet 4-6; Phase 3 unchanged (also Claude Sonnet 4-6)
- Logs directory now tracked in git for future audits
