# Bible Study Agent

Personal Bible study automation — daily devotions, weekly sermon study, interactive exegesis.
Standalone sub-agent running alongside the Chief of Staff system on the same server.

**Cost: ~$0.30/month** — Gemini free tier for everything except Phase 3 synthesis
(Claude Sonnet, ~$0.05-0.08 per journal entry).

---

## What Requires Your Input vs What's Automated

**You do nothing — fully automated:**
- Daily devotions (Mon–Sat, 6:00 AM) — generated from the weekly passage, sent to Telegram + email
- Sunday evening sermon fetch (6:00 PM, 8:00 PM retry) — scrapes abfboone.com, extracts passage,
  runs Phase 1 exegetical study, runs Phase 2 sermon analysis, sends you one notification

**Your only weekly action:**
- When you're ready: say *"write the journal entry"* → Phase 3 runs, saved to knowledge base

**On demand — just say it naturally:**
- *"Study Psalm 46"* → Phase 1 on any passage, any time
- *"Synthesize that"* → Phase 3 on a side study
- *"Save this study"* → writes side study to knowledge base
- *"Give me today's devotion"* → manual devotion trigger
- *"Fetch the sermon"* → manually trigger the Sunday pipeline if cron missed it
- Any Bible question → dialogue using your full theological framework

---

## Chief of Staff Knowledge Base Integration

This bot is **read-write connected** to the Chief of Staff knowledge base.

### What it reads (on every AI call)

| File | Purpose |
|---|---|
| `~/chief-of-staff/knowledge-base/context/STYLE.md` | Your reasoning patterns and voice — used to ground application sections in devotions and Phase 3 syntheses |
| `~/chief-of-staff/knowledge-base/context/GOALS.md` | Current priorities and vocational context — used to make applications relevant to your actual situation |

These files are read at runtime and injected into the system prompt. The Bible study bot
never modifies them. If they don't exist yet, the bot degrades gracefully — it just skips
the personal context injection.

### What it writes

| Location | Content |
|---|---|
| `~/chief-of-staff/knowledge-base/personal/bible-study/study-[passage].md` | Complete weekly study (Phase 1 + 2 + 3 together) on Phase 3 completion |
| `~/chief-of-staff/knowledge-base/personal/bible-study/side-study-[passage]-[date].md` | Side studies, on explicit save request |
| `~/chief-of-staff/knowledge-base/personal/bible-study/[YYYY-MM-DD].md` | Daily devotion text (every day, written automatically) |

### How it connects to the enrichment pipeline

Once Stage 2 enrichment is running, add one entry to `~/chief-of-staff/bot/config.py`:

```python
PROJECT_TYPES = {
    ...existing entries...
    "personal/bible-study": "devotional_study",   # ADD THIS
}
```

After that, every study file written by this bot will be automatically picked up on the
next overnight enrichment run, indexed into ChromaDB, and available to the Stage 3 agent.
Your spiritual formation thinking becomes part of the broader knowledge base without
any additional steps.

---

## Sunday Evening Flow (Automated)

```
6:00 PM Sunday — cron fires run_sermon_fetch.py
    ↓
Fetch https://www.abfboone.com/luke/ — find most recent sermon
    ↓
Already fetched this week? → exit silently
    ↓
Extract passage from title ("LUKE 14:12-24" → "Luke 14:12-24")
Set as active weekly passage in state.json
Fetch and store full transcript
    ↓
Run Phase 1 — Exegetical Study (Gemini free)
Run Phase 2 — Sermon Analysis (Gemini free)
    ↓
Telegram: "✅ Weekly study ready — Luke 14:12-24. Say 'write the journal entry' when ready."

8:00 PM — retry run fires
    Already fetched? → exit silently (no duplicate messages)
    Not yet posted? → notify once
```

---

## Daily Devotion Flow (Automated)

```
6:00 AM Mon–Sat — cron fires run_devotion.py
    ↓
Read active passage from state.json
    ↓
No passage set? → Telegram reminder to set one. Exit.
    ↓
Select day's angle (Mon=Observation, Tue=Key Term, Wed=Cross-Reference,
                    Thu=Redemptive-Historical, Fri=Application, Sat=Summary)
    ↓
Read STYLE.md + GOALS.md from Chief of Staff KB (personalisation context)
    ↓
Generate devotion via Gemini — 400-600 words
    ↓
Send to Telegram
Send to email subscriber list (if configured)
Write to ~/chief-of-staff/knowledge-base/personal/bible-study/YYYY-MM-DD.md
```

---

## File Structure

```
bible-study-bot/
├── bot.py                    # Telegram handler — natural language intent routing
├── devotion_agent.py         # Daily devotion generation + distribution
├── sermon_fetcher.py         # Sunday pipeline — fetch, extract, Phase 1, Phase 2
├── study_session.py          # Phase 1/2/3 study session logic
├── gemini_client.py          # AI client — Gemini (free) + Claude Sonnet (Phase 3)
├── system_prompts.py         # All prompts — charter, phases, devotion, dialogue
├── state.py                  # state.json read/write
├── run_devotion.py           # Cron entry point — daily devotion
├── run_sermon_fetch.py       # Cron entry point — Sunday pipeline
├── state.json                # Current session state
├── subscribers.json          # Email distribution list
├── sermons/                  # Stored sermon transcripts
│   └── sermon_YYYY-MM-DD.txt
├── logs/                     # Devotion and cron logs
│   └── devotion_YYYY-MM-DD.txt
└── .env                      # Secrets — never commit
```

---

## Setup

### Step 1 — Gemini API key (free, 2 minutes)
1. Go to https://aistudio.google.com
2. Sign in with Google → "Get API key" → "Create API key in new project"
3. Copy the key

### Step 2 — New Telegram bot
1. Open Telegram → search @BotFather → send `/newbot`
2. Follow prompts, copy the token BotFather returns

### Step 3 — Get your Telegram chat ID
Send any message to your new bot, then visit:
`https://api.telegram.org/bot[YOUR_TOKEN]/getUpdates`
Find `"chat":{"id":YOUR_CHAT_ID}` in the JSON response.

### Step 4 — Configure environment
```bash
cd ~/bible-study-bot
cp .env.example .env
# Edit .env — add Gemini key, Telegram token, chat ID,
# and your existing Anthropic API key from Chief of Staff
```

### Step 5 — Install dependencies
```bash
pip install -r requirements.txt --break-system-packages
```

### Step 6 — Create KB directory and add project type
```bash
mkdir -p ~/chief-of-staff/knowledge-base/personal/bible-study
```

Then in `~/chief-of-staff/bot/config.py`, add to PROJECT_TYPES:
```python
"personal/bible-study": "devotional_study",
```

### Step 7 — Add email subscribers (optional)
Edit `subscribers.json`:
```json
{
  "subscribers": [
    "friend@example.com",
    "another@example.com"
  ]
}
```

### Step 8 — Test manually before setting cron
```bash
# Test sermon fetcher (runs the full pipeline)
python sermon_fetcher.py

# Check state.json was updated
cat state.json

# Test devotion (requires active passage in state.json)
python devotion_agent.py

# Start the bot
python bot.py
```

### Step 9 — Set up cron jobs
```bash
crontab -e
```

Add these four lines:
```
# Daily devotion — Mon through Sat at 6:00 AM
0 6 * * 1-6 cd /home/daniel/bible-study-bot && python run_devotion.py >> logs/cron.log 2>&1

# Sunday sermon pipeline — first attempt 6:00 PM
0 18 * * 0 cd /home/daniel/bible-study-bot && python run_sermon_fetch.py >> logs/cron.log 2>&1

# Sunday sermon pipeline — retry 8:00 PM
0 20 * * 0 cd /home/daniel/bible-study-bot && python run_sermon_fetch.py >> logs/cron.log 2>&1
```

### Step 10 — Run bot as persistent process
```bash
screen -S bible-bot
python bot.py
# Ctrl+A then D to detach
# Reconnect: screen -r bible-bot
```

---

## Your Weekly Interaction

**Sunday after service:**
Nothing. The bot handles it.

**Sunday evening (you receive):**
> ✅ Weekly study ready — Luke 14:25-35
> Phase 1 and Phase 2 complete.
> Say "write the journal entry" when you're ready for Phase 3.

**Monday–Saturday 6:00 AM (you receive):**
> 📖 Morning Devotion — Tuesday, March 24
> Luke 14:25-35 | Key Term
> [devotion text]

**Whenever you're ready during the week:**
Just say: *"write the journal entry"*

That's it for the weekly study.

---

## Natural Language Examples

| You say | Bot does |
|---|---|
| *"Write the journal entry"* | Phase 3 synthesis → saved to KB |
| *"Study Psalm 46 for me"* | Side study Phase 1 |
| *"Synthesize that"* | Phase 3 on current side study |
| *"Save this study"* | Writes side study to KB |
| *"Give me today's devotion"* | Triggers devotion manually |
| *"Fetch the sermon"* | Runs Sunday pipeline on demand |
| *"Where are we in the study?"* | Shows current state |
| *"What is agonizomai?"* | Bible dialogue |
| *"What do you think about Romans 8?"* | Bot asks: full study or a question? |

---

## Stage 3 Integration (Future)

When the Chief of Staff Stage 3 agent is built, register this as a sub-agent tool:
```python
"bible_study_agent": {
    "capability": "bible_study",
    "state_file": "~/bible-study-bot/state.json",
    "kb_path": "~/chief-of-staff/knowledge-base/personal/bible-study/",
}
```
The agent will be able to query active passage, study phase, and surface insights from
your study history during Stage 3 conversations.
