# Claude Code Handoff — Bible Study Agent

## What You're Building

A personal Bible study automation system. All code is written and ready.
Your job is to transfer the files to the server, configure credentials, install dependencies,
test each component, and set up the cron jobs and persistent process.

No code generation is required. Follow the steps in order and verify each one before proceeding.

---

## What You Need Before Starting

Have these four things ready before opening the terminal:

1. **Gemini API key** — get at https://aistudio.google.com → "Get API key" (free, 2 min)
2. **Telegram bot token** — create via @BotFather in Telegram (`/newbot`)
3. **Telegram chat ID** — send any message to your new bot, then visit:
   `https://api.telegram.org/bot[YOUR_TOKEN]/getUpdates` and find `"chat":{"id":XXXXXXX}`
4. **Anthropic API key** — copy from the Chief of Staff system:
   `grep ANTHROPIC ~/chief-of-staff/.env`

---

## Step 1 — Transfer Files to Server

From your Mac, open Terminal and run:

```bash
scp -r ~/Downloads/bible-study-bot daniel@100.85.175.12:~/bible-study-bot
```

Verify the transfer:

```bash
ssh daniel@100.85.175.12 "ls ~/bible-study-bot/"
```

Expected: all 14 files listed — `bot.py`, `devotion_agent.py`, `sermon_fetcher.py`,
`study_session.py`, `gemini_client.py`, `system_prompts.py`, `state.py`, `run_devotion.py`,
`run_sermon_fetch.py`, `state.json`, `subscribers.json`, `.env.example`, `requirements.txt`, `README.md`

---

## Step 2 — SSH Into the Server

```bash
ssh daniel@100.85.175.12
cd ~/bible-study-bot
```

All remaining steps run on the server.

---

## Step 3 — Configure Environment

```bash
cp .env.example .env
nano .env
```

Fill in all five values:
```
TELEGRAM_BOT_TOKEN=   ← from BotFather
TELEGRAM_CHAT_ID=     ← from getUpdates
GEMINI_API_KEY=       ← from Google AI Studio
ANTHROPIC_API_KEY=    ← from ~/chief-of-staff/.env
GMAIL_ADDRESS=        ← your Gmail (or leave blank for now)
GMAIL_APP_PASSWORD=   ← App Password from myaccount.google.com/apppasswords (or leave blank)
```

Save: `Ctrl+X → Y → Enter`

Verify no secrets are missing:
```bash
grep -v "^#" .env | grep -v "^$"
```

All five lines should have real values, not placeholder text.

---

## Step 4 — Install Dependencies

```bash
pip install -r requirements.txt --break-system-packages
```

Verify:
```bash
python3 -c "import aiogram; import google.generativeai; import anthropic; import bs4; print('All dependencies OK')"
```

---

## Step 5 — Create Knowledge Base Directory and Register Project Type

```bash
mkdir -p ~/chief-of-staff/knowledge-base/personal/bible-study
```

Open the Chief of Staff config and add the bible-study project type:
```bash
nano ~/chief-of-staff/bot/config.py
```

Find the `PROJECT_TYPES` dictionary and add this line:
```python
"personal/bible-study": "devotional_study",
```

Save and close. This connects the Bible study bot to the Stage 2 enrichment pipeline —
study files written here will be picked up automatically on the next overnight run.

---

## Step 6 — Test the Sermon Fetcher

This runs the full Sunday pipeline: fetch → extract passage → set active → Phase 1 → Phase 2.

```bash
python3 sermon_fetcher.py
```

Expected output:
```
[sermon_fetcher] Checking https://www.abfboone.com/luke/...
[sermon_fetcher] New sermon: LUKE 14:12-24 (March 15, 2026)
[sermon_fetcher] Active passage set: Luke 14:12-24
[sermon_fetcher] Running Phase 1 for Luke 14:12-24...
[sermon_fetcher] Phase 1 complete (XXXX chars).
[sermon_fetcher] Running Phase 2 sermon analysis...
[sermon_fetcher] Phase 2 complete (XXXX chars).
```

Verify state was written correctly:
```bash
cat state.json
```

Should show `active_passage` set, `sermon_fetched: true`, `study_phase: 2`,
and non-null `phase1_output` and `phase2_output`.

Verify sermon transcript stored:
```bash
ls sermons/
head -5 sermons/sermon_*.txt
```

---

## Step 7 — Test the Devotion Generator

```bash
python3 devotion_agent.py
```

Expected: devotion text printed to terminal + message sent to Telegram.
Check your Telegram — devotion should arrive within a few seconds.

---

## Step 8 — Start the Bot

```bash
screen -S bible-bot
python3 bot.py
```

You should see: `Bible Study Bot starting...`

Open Telegram and send these three test messages to your new bot:
1. *"Where are we in the study?"* → should return current study status
2. *"What is agonizomai?"* → should return a theological response
3. *"Write the journal entry"* → should run Phase 3 and confirm KB save

Then detach from screen so the bot keeps running after you disconnect:
```
Ctrl+A then D
```

Verify it's still running:
```bash
screen -list
```

---

## Step 9 — Set Up Cron Jobs

```bash
crontab -e
```

Add these three lines (adjust path if username differs from `daniel`):

```
# Bible Study — daily devotion Mon–Sat 6:00 AM
0 6 * * 1-6 cd /home/daniel/bible-study-bot && python3 run_devotion.py >> logs/cron.log 2>&1

# Bible Study — Sunday sermon pipeline, first attempt 6:00 PM
0 18 * * 0 cd /home/daniel/bible-study-bot && python3 run_sermon_fetch.py >> logs/cron.log 2>&1

# Bible Study — Sunday sermon pipeline, retry 8:00 PM
0 20 * * 0 cd /home/daniel/bible-study-bot && python3 run_sermon_fetch.py >> logs/cron.log 2>&1
```

Save and close. Verify:
```bash
crontab -l
```

---

## Step 10 — Full End-to-End Smoke Test

Reset state so the fetcher runs again, then re-run the pipeline:

```bash
python3 -c "
import json
with open('state.json') as f: s = json.load(f)
s['sermon_date'] = None
s['sermon_fetched'] = False
with open('state.json', 'w') as f: json.dump(s, f, indent=2)
print('State reset — ready for smoke test')
"

python3 run_sermon_fetch.py
```

Check Telegram — you should receive:
> ✅ Weekly study ready — Luke 14:12-24
> Phase 1 and Phase 2 complete.
> Say "write the journal entry" when you're ready for Phase 3.

Reply to the bot: *"write the journal entry"*

Verify the study file landed in the KB:
```bash
ls ~/chief-of-staff/knowledge-base/personal/bible-study/
```

If a file is there — the full pipeline is working end-to-end.

---

## Step 11 — Add Email Subscribers (Optional, Do Later)

```bash
nano ~/bible-study-bot/subscribers.json
```

Replace the placeholder:
```json
{
  "subscribers": [
    "person@example.com"
  ]
}
```

Gmail App Password setup: myaccount.google.com → Security → App Passwords.
Add the 16-character password to `.env` as `GMAIL_APP_PASSWORD`.

---

## After a Server Reboot

The screen session is lost on reboot. Restart the bot with:

```bash
screen -S bible-bot
cd ~/bible-study-bot
python3 bot.py
# Ctrl+A then D
```

Cron jobs survive reboots automatically — no action needed for those.

---

## Debugging Reference

| Problem | Where to look |
|---|---|
| Cron not firing | `crontab -l` to verify entries exist |
| Devotion not arriving | `tail -30 logs/cron.log` |
| Bot not responding | `screen -r bible-bot` to see live output |
| Sermon fetch failed | `python3 sermon_fetcher.py` manually, read the error |
| State looks wrong | `cat state.json` |
| KB file not written | `ls ~/chief-of-staff/knowledge-base/personal/bible-study/` |

---

## What NOT to Do

- Do not run `cat .env` — use `grep SPECIFIC_KEY .env`
- Do not create a second Telegram bot — use the token from BotFather
- Do not touch `.last_enriched` in the Chief of Staff directory
- Do not modify `state.json` by hand except for the smoke test reset above
