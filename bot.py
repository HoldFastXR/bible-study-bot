"""
bot.py
Bible Study Agent — natural language interface.

No slash commands required. The bot reads intent from plain conversation.

Intent classifier (fast Gemini call) routes each message to one of:
  SET_PASSAGE        "This week we're in Luke 15"
  RUN_PHASE1         "Let's study this week's passage" / "Run the exegesis"
  RUN_PHASE2         "Add the sermon" / "Run the sermon analysis"
  RUN_PHASE3         "Synthesize this" / "Write the journal entry"
  SIDE_STUDY         "Study Psalm 46 for me" / "I want to look at Romans 8"
  SIDE_JOURNAL       "Now synthesize that" / "Journal entry for this one"
  SAVE_STUDY         "Save that to the knowledge base"
  DEVOTION           "Give me today's devotion"
  STATUS             "Where are we in the study?" / "What's the current passage?"
  CLARIFY_PASSAGE    User mentions a passage without clear study intent → ask what they want
  DIALOGUE           General Bible question or conversation

Slash commands are preserved as fallbacks but never required.
"""

import asyncio
import json
import logging
import os
import re
import subprocess
from pathlib import Path

import google.generativeai as genai
from aiogram import Bot, Dispatcher
from aiogram.filters import Command, CommandObject
from aiogram.types import FSInputFile, Message
from dotenv import load_dotenv

from devotion_agent import run as run_devotion
from esv_client import get_passage_text
from gemini_client import generate_with_history
from html_renderer import write_study_html
import logos_io

LOGOS_WEEK_SCRIPT = "/home/daniel/chief-of-staff/run_logos_week.sh"
LOGOS_JOURNAL_SCRIPT = "/home/daniel/chief-of-staff/run_logos_journal.sh"
LOGOS_STUDY_SCRIPT = "/home/daniel/chief-of-staff/run_logos_study.sh"
from state import get_active_passage, set_active_passage
from study_session import (
    get_status_message,
    write_side_study_to_kb,
)
from system_prompts import DIALOGUE_SYSTEM_PROMPT

import sys as _sys
_sys.path.insert(0, str(__import__('pathlib').Path.home()))
from shared.conversation import ConversationStore

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

bot = Bot(token=TELEGRAM_BOT_TOKEN)
dp = Dispatcher()

_conv_store = ConversationStore("logos", max_exchanges=20, ttl_seconds=86400)
try:
    _conv_store.evict_stale()
except Exception:
    pass

# In-memory stores (dialogue_history replaced by SQLite-backed _conv_store)
side_study_session: dict = {
    "passage": None,
    "phase1": None,
    "phase2": None,
    "phase3": None,
}

# Pending clarification state — when bot asks "study it or ask a question?"
pending_clarification: dict = {
    "active": False,
    "passage": None,
}


# ── Intent Classifier ─────────────────────────────────────────────────────────

INTENT_SYSTEM_PROMPT = """
You are an intent classifier for a personal Bible study Telegram bot.
Classify the user's message into exactly one intent from this list.
Return ONLY a JSON object — no explanation, no markdown, no preamble.

INTENTS:
  SET_PASSAGE      — User is telling the bot the passage for this week's sermon study.
                     May say "this week", "Pastor is preaching", "Sunday's text", or just name a passage with week context.
                     Extract the passage reference if present.
  RUN_PHASE1       — User wants to run Phase 1 exegetical study on the weekly passage.
                     Phrases like: "let's study", "run the exegesis", "start the study", "phase 1", "do the exegetical work"
  RUN_PHASE2       — User wants to run Phase 2 sermon insights on the weekly passage.
                     Phrases like: "add the sermon", "sermon analysis", "phase 2", "run phase 2", "use the sermon"
  RUN_PHASE3       — User wants to run Phase 3 synthesis/journal on the weekly passage.
                     Phrases like: "synthesize", "write the journal entry", "journal this", "phase 3", "journal entry"
  SIDE_STUDY       — User wants to study a specific passage that is NOT framed as this week's sermon.
                     Phrases like: "study [passage]", "look at [passage]", "can you study", "I want to work through"
                     Extract the passage reference.
  SIDE_JOURNAL     — User wants Phase 3 synthesis of the current side study session.
                     Phrases like: "now synthesize that", "journal entry for this one", "write a synthesis", "journal the side study"
  SAVE_STUDY       — User wants to save the side study to the knowledge base.
                     Phrases like: "save that", "log it", "add to knowledge base", "save this study"
  DEVOTION         — User wants today's devotion.
                     Phrases like: "devotion", "today's devotion", "morning reading", "give me the devotion"
  STATUS           — User wants to know current study state, active passage, or study progress.
                     Phrases like: "where are we", "what's the current passage", "study status", "what phase"
  FETCH_SERMON     — User wants to manually trigger the sermon fetch pipeline.
                     Phrases like: "fetch the sermon", "get this week's sermon", "check for the sermon",
                     "run the pipeline", "grab the sermon transcript"
  CLARIFY_PASSAGE  — User mentions a Bible passage or asks about a passage but intent is ambiguous —
                     could be a question or a study request. Use this when you genuinely cannot tell.
                     Extract the passage reference.
  DIALOGUE         — General Bible question, theological question, or conversational message.
                     No clear action intent.
                     IMPORTANT: Messages containing deferred timing language — "tomorrow", "later",
                     "at 5am", "tonight", "as scheduled", "as designed", "on schedule", "when ready",
                     "this evening", "in the morning" — are ALWAYS DIALOGUE, even if they mention
                     an action. The bot should respond conversationally confirming the plan, not
                     execute the action immediately.

Return format (always valid JSON, nothing else):
{
  "intent": "INTENT_NAME",
  "passage": "extracted passage or null",
  "confidence": "high|medium|low"
}

Examples:
  "This week we're in Luke 15:1-10" → {"intent": "SET_PASSAGE", "passage": "Luke 15:1-10", "confidence": "high"}
  "Let's do the study" → {"intent": "RUN_PHASE1", "passage": null, "confidence": "high"}
  "Add the sermon now" → {"intent": "RUN_PHASE2", "passage": null, "confidence": "high"}
  "Write the journal entry" → {"intent": "RUN_PHASE3", "passage": null, "confidence": "high"}
  "Can you study Psalm 46 for me?" → {"intent": "SIDE_STUDY", "passage": "Psalm 46", "confidence": "high"}
  "I want to look at Romans 8:28-39" → {"intent": "SIDE_STUDY", "passage": "Romans 8:28-39", "confidence": "high"}
  "Now synthesize that" → {"intent": "SIDE_JOURNAL", "passage": null, "confidence": "high"}
  "Save that to the KB" → {"intent": "SAVE_STUDY", "passage": null, "confidence": "high"}
  "Fetch the sermon" → {"intent": "FETCH_SERMON", "passage": null, "confidence": "high"}
  "What do you think about Psalm 46?" → {"intent": "CLARIFY_PASSAGE", "passage": "Psalm 46", "confidence": "high"}
  "What is agonizomai?" → {"intent": "DIALOGUE", "passage": null, "confidence": "high"}
  "How does covenant theology work?" → {"intent": "DIALOGUE", "passage": null, "confidence": "high"}
  "Send me the devotion tomorrow morning" → {"intent": "DIALOGUE", "passage": null, "confidence": "high"}
  "Run the study at 5am" → {"intent": "DIALOGUE", "passage": null, "confidence": "high"}
  "Proceed as designed" → {"intent": "DIALOGUE", "passage": null, "confidence": "high"}
  "Yes, carry on as scheduled" → {"intent": "DIALOGUE", "passage": null, "confidence": "high"}
  "Do it later tonight" → {"intent": "DIALOGUE", "passage": null, "confidence": "high"}
  "Run the devotion on schedule" → {"intent": "DIALOGUE", "passage": null, "confidence": "high"}
  "Send it tomorrow" → {"intent": "DIALOGUE", "passage": null, "confidence": "high"}
"""


def classify_intent(text: str) -> dict:
    """
    Fast Gemini call to classify message intent.
    Returns dict with intent, passage, confidence.
    Falls back to DIALOGUE on any failure.
    """
    try:
        model = genai.GenerativeModel(
            model_name="gemini-2.5-flash",
            system_instruction=INTENT_SYSTEM_PROMPT
        )
        response = model.generate_content(text)
        raw = response.text.strip()

        # Strip markdown fences if present
        raw = re.sub(r"```json|```", "", raw).strip()

        result = json.loads(raw)
        return result

    except Exception as e:
        log.warning(f"Intent classification failed: {e} — defaulting to DIALOGUE")
        return {"intent": "DIALOGUE", "passage": None, "confidence": "low"}


# ── Helpers ───────────────────────────────────────────────────────────────────

def is_authorized(message: Message) -> bool:
    return str(message.chat.id) == str(TELEGRAM_CHAT_ID)


def _logos_chat_id() -> int:
    """Canonical chat_id key for Logos' single user."""
    try:
        return int(TELEGRAM_CHAT_ID)
    except (TypeError, ValueError):
        return 0


def strip_html(text: str) -> str:
    """Remove HTML tags (e.g. <sup>25</sup>) from text."""
    return re.sub(r'<[^>]+>', '', text)


async def send_long(chat_id: str, text: str):
    text = strip_html(text)
    chunks = [text[i:i+4000] for i in range(0, len(text), 4000)]
    for chunk in chunks:
        await bot.send_message(chat_id, chunk)


def _kick_cc_detached(script: str, *args: str) -> bool:
    """Fire-and-forget CC run. The run script handles its own Telegram notification."""
    try:
        subprocess.Popen(
            [script, *args],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return True
    except Exception as e:
        log.error(f"failed to spawn {script}: {e}")
        return False


async def _await_cc_run(script: str, *args: str, timeout: int = 900) -> tuple[int, str, str]:
    """Run a CC script and await completion. Returns (returncode, stdout, stderr)."""
    proc = await asyncio.create_subprocess_exec(
        script, *args,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill(); await proc.communicate()
        return 124, "", "timeout"
    return proc.returncode, out.decode(errors="replace"), err.decode(errors="replace")


async def send_html_file(chat_id: str, path: Path, caption: str,
                         display_name: str | None = None):
    """Send a pre-rendered HTML document via Telegram, with text fallback.

    `display_name` overrides the filename shown in the Telegram chat without
    renaming the file on disk (e.g. "1. Exegetical Study of Luke 16:16-18").
    """
    try:
        filename = display_name or path.name
        if not filename.lower().endswith(".html"):
            filename = f"{filename}.html"
        await bot.send_document(
            chat_id, FSInputFile(str(path), filename=filename), caption=caption,
        )
    except Exception as e:
        log.error(f"send_document failed for {path}: {e}")
        await bot.send_message(chat_id, f"⚠️ Could not send {path.name}: {e}")


async def send_study_html(chat_id: str, title: str, subtitle: str, body: str, slug: str,
                          caption: str, passage: str | None = None):
    """
    Render a long-form study/journal output to a styled HTML file and send it as a
    Telegram document so Daniel can read it in a browser rather than in-chat.
    When a passage is given, its ESV text is fetched and shown above the study.
    Falls back to chunked plain text if rendering or upload fails.
    """
    try:
        loop = asyncio.get_event_loop()
        scripture = (
            await loop.run_in_executor(None, get_passage_text, passage)
            if passage else None
        )
        path = await loop.run_in_executor(
            None, write_study_html, title, subtitle, body, slug, scripture
        )
        await bot.send_document(chat_id, FSInputFile(path), caption=caption)
    except Exception as e:
        log.error(f"HTML document send failed ({e}); falling back to text.")
        await send_long(chat_id, body)


# ── Intent Handlers ───────────────────────────────────────────────────────────

async def handle_set_passage(message: Message, passage: str):
    set_active_passage(passage)
    kicked = _kick_cc_detached(LOGOS_WEEK_SCRIPT, passage)
    if kicked:
        await message.answer(
            f"✅ Weekly passage set: *{passage}*\n\n"
            f"Kicking the Logos weekly batch (Phase 1 + Mon–Sat devotions). "
            f"I'll notify you when the week is ready — typically a few minutes.",
            parse_mode="Markdown"
        )
    else:
        await message.answer(
            f"✅ Weekly passage set: *{passage}*\n\n"
            f"⚠️ Could not launch the weekly batch — say *generate the week* to retry.",
            parse_mode="Markdown"
        )


async def handle_run_phase1(message: Message):
    passage = get_active_passage()
    if not passage:
        await message.answer(
            "No weekly passage set yet. Just tell me the passage — "
            "something like *\"This week we're in Luke 15\"* — and I'll set it up.",
            parse_mode="Markdown"
        )
        return

    # Prefer the pre-generated Phase 1 HTML from this week's Logos batch — but
    # only if the batch was generated for the currently-active passage. If the
    # manifest passage doesn't match, the batch is stale; fall through and kick
    # a fresh one rather than serve content from a different week's passage.
    html = logos_io.phase_path("phase1", "html")
    if html.exists() and logos_io.passage_matches(passage):
        await send_html_file(
            str(message.chat.id), html,
            caption=f"📖 Phase 1 — exegetical study of {passage}.",
            display_name=f"1. Exegetical Study of {passage}",
        )
        return

    # Not generated for this passage yet — kick the batch and tell Daniel.
    kicked = _kick_cc_detached(LOGOS_WEEK_SCRIPT, passage)
    if kicked:
        await message.answer(
            f"📖 No Phase 1 yet for *{passage}* — kicking the weekly batch now. "
            f"I'll send Phase 1 + Mon–Sat devotions when it finishes (typically a few minutes).",
            parse_mode="Markdown"
        )
    else:
        await message.answer(
            "⚠️ Could not launch the weekly batch. Check `logos_run.log`.",
            parse_mode="Markdown"
        )


async def handle_run_phase2(message: Message):
    await message.answer(
        "Phase 2 and Phase 3 are now produced together by Claude in one run "
        "(sermon insights + synthesis, building on the already-locked Phase 1). "
        "Just say *write the journal entry* and I'll run it.",
        parse_mode="Markdown"
    )


async def handle_run_phase3(message: Message):
    passage = get_active_passage()
    if not passage:
        await message.answer("No weekly passage set yet.", parse_mode="Markdown")
        return

    html = logos_io.phase_path("phase3", "html")
    if html.exists() and logos_io.passage_matches(passage):
        await send_html_file(
            str(message.chat.id), html,
            caption=f"📓 Phase 3 — journal synthesis for {passage}."
        )
        return

    # Need to run /logos-journal. Phase 1 must exist AND match the active passage —
    # otherwise the journal would build on stale exegesis.
    if not logos_io.phase_path("phase1", "md").exists() or not logos_io.passage_matches(passage):
        await message.answer(
            "⚠️ Phase 1 for the current passage isn't ready yet. "
            "Re-set the passage to kick a fresh weekly batch, then try again.",
            parse_mode="Markdown"
        )
        return

    await message.answer(
        f"📓 Writing the journal entry for *{passage}* — Claude is doing Phase 2 (sermon) "
        f"+ Phase 3 (synthesis) in one pass. Back in a few minutes...",
        parse_mode="Markdown"
    )
    rc, out, err = await _await_cc_run(LOGOS_JOURNAL_SCRIPT)
    if rc != 0 or not html.exists():
        await message.answer(
            f"⚠️ Journal run failed (rc={rc}). Check `logos_run.log` for details.",
            parse_mode="Markdown"
        )
        return
    await send_html_file(
        str(message.chat.id), html,
        caption=f"📓 Phase 3 — journal synthesis for {passage}.",
        display_name=f"3. Journal Synthesis for {passage}",
    )
    await message.answer("✅ Study saved to knowledge base.", parse_mode="Markdown")


async def handle_side_study(message: Message, passage: str):
    await message.answer(
        f"📖 Running side study of *{passage}* — Claude is producing Phase 1 + "
        f"Phase 3 (no sermon, text-first). Back in a few minutes...\n"
        f"_(Weekly passage unchanged.)_",
        parse_mode="Markdown"
    )
    rc, out, err = await _await_cc_run(LOGOS_STUDY_SCRIPT, passage)
    if rc != 0:
        await message.answer(
            f"⚠️ Side study failed (rc={rc}). Check `logos_run.log`.",
            parse_mode="Markdown"
        )
        return
    out_dir = Path(out.strip().splitlines()[-1]) if out.strip() else None
    if not out_dir or not out_dir.exists():
        await message.answer("⚠️ Side study finished but output dir not found.")
        return

    side_study_session["passage"] = passage
    side_study_session["dir"] = str(out_dir)
    side_study_session["phase1"] = None
    side_study_session["phase2"] = None
    side_study_session["phase3"] = None

    chat_id = str(message.chat.id)
    p1 = out_dir / "phase1.html"
    p3 = out_dir / "phase3.html"
    if p1.exists():
        await send_html_file(
            chat_id, p1,
            caption=f"📖 Phase 1 — side study of {passage}.",
            display_name=f"1. Exegetical Study of {passage}",
        )
    if p3.exists():
        await send_html_file(
            chat_id, p3,
            caption=f"📓 Phase 3 — synthesis for {passage}.",
            display_name=f"3. Journal Synthesis for {passage}",
        )
    await message.answer(
        f"Side study complete for *{passage}*. Say *save this study* to log it to the "
        f"knowledge base.",
        parse_mode="Markdown"
    )


async def handle_side_journal(message: Message):
    # The side-study CC run produces Phase 1 + Phase 3 together. There's nothing
    # extra to synthesize — just re-send the existing synthesis HTML.
    out_dir = side_study_session.get("dir")
    if not out_dir:
        await message.answer(
            "No side study in progress. Just name a passage — "
            "something like *\"study Psalm 46\"* — to begin.",
            parse_mode="Markdown"
        )
        return
    passage = side_study_session.get("passage", "passage")
    p3 = Path(out_dir) / "phase3.html"
    if p3.exists():
        await send_html_file(
            str(message.chat.id), p3,
            caption=f"📓 Phase 3 — synthesis for {passage}.",
            display_name=f"3. Journal Synthesis for {passage}",
        )
    else:
        await message.answer(
            "Phase 3 wasn't produced for that side study (unexpected). "
            "Say *study [passage]* to re-run.",
            parse_mode="Markdown"
        )


async def handle_fetch_sermon(message: Message):
    """Manual trigger for the full Sunday pipeline."""
    await message.answer(
        "📡 Checking for this week's sermon...",
        parse_mode="Markdown"
    )
    loop = asyncio.get_event_loop()

    def _run_fetch():
        from sermon_fetcher import run as run_fetch
        return run_fetch(notify_telegram=None)  # Bot handles messaging directly

    result = await loop.run_in_executor(None, _run_fetch)

    if result.get("reason") == "already_fetched":
        await message.answer(
            "Already have this week's sermon loaded. "
            "Say *\"write the journal entry\"* when you're ready for Phase 3.",
            parse_mode="Markdown"
        )
    elif not result.get("found"):
        await message.answer(
            "⚠️ No new sermon found on the site yet. "
            "Try again later or check abfboone.com directly.",
            parse_mode="Markdown"
        )
    elif "error" in result:
        await message.answer(f"⚠️ Pipeline error: {result['error']}", parse_mode="Markdown")
    else:
        passage = result.get("passage", "this week's passage")
        await message.answer(
            f"✅ *Weekly study ready — {passage}*\n\n"
            f"Phase 1 and Phase 2 complete.\n"
            f"Say *\"write the journal entry\"* when you're ready for Phase 3.",
            parse_mode="Markdown"
        )


async def handle_save_study(message: Message):
    out_dir = side_study_session.get("dir")
    passage = side_study_session.get("passage")
    if not out_dir or not passage:
        await message.answer("No side study to save yet.", parse_mode="Markdown")
        return

    p1 = (Path(out_dir) / "phase1.md")
    p3 = (Path(out_dir) / "phase3.md")
    phase1_md = p1.read_text(encoding="utf-8") if p1.exists() else "(Phase 1 not found)"
    phase3_md = p3.read_text(encoding="utf-8") if p3.exists() else "(Phase 3 not run)"

    loop = asyncio.get_event_loop()
    filepath = await loop.run_in_executor(
        None,
        write_side_study_to_kb,
        passage,
        phase1_md,
        phase3_md,
        None,
    )
    await message.answer(
        f"✅ *{passage}* saved to knowledge base.",
        parse_mode="Markdown"
    )


async def handle_clarify_passage(message: Message, passage: str):
    """Ask whether they want to study the passage or ask a question about it."""
    pending_clarification["active"] = True
    pending_clarification["passage"] = passage
    await message.answer(
        f"*{passage}* — did you want me to run a full exegetical study, "
        f"or were you asking a question about it?",
        parse_mode="Markdown"
    )


async def handle_dialogue(message: Message, text: str):
    passage = get_active_passage()
    context_note = f"\n\n[Current weekly passage: {passage}]" if passage else ""

    try:
        loop = asyncio.get_event_loop()
        _cid = _logos_chat_id()
        prior = _conv_store.get_history(_cid) or None
        response = await loop.run_in_executor(
            None,
            generate_with_history,
            DIALOGUE_SYSTEM_PROMPT + context_note,
            prior,
            text,
            False,
        )
        _conv_store.append_exchange(
            _cid,
            {"role": "user", "parts": [text]},
            {"role": "model", "parts": [response]},
        )
        await send_long(str(message.chat.id), response)

    except Exception as e:
        log.error(f"Dialogue error: {e}")
        await message.answer(f"Something went wrong: {e}")


# ── Pending Clarification Handler ─────────────────────────────────────────────

async def resolve_pending_clarification(message: Message, text: str) -> bool:
    """
    If there's a pending passage clarification, try to resolve it.
    Returns True if handled, False if clarification is still unclear.
    """
    if not pending_clarification["active"]:
        return False

    passage = pending_clarification["passage"]
    text_lower = text.lower()

    study_signals = [
        "study", "exegesis", "phase 1", "full study", "run it",
        "yes", "yeah", "go ahead", "do it", "let's do", "study it"
    ]
    question_signals = [
        "question", "ask", "just asking", "no", "dialogue",
        "what do you think", "answer", "tell me about"
    ]

    if any(s in text_lower for s in study_signals):
        pending_clarification["active"] = False
        pending_clarification["passage"] = None
        await handle_side_study(message, passage)
        return True

    if any(s in text_lower for s in question_signals):
        pending_clarification["active"] = False
        pending_clarification["passage"] = None
        await handle_dialogue(message, f"Tell me about {passage}")
        return True

    # Still unclear — ask once more plainly
    await message.answer(
        f"Just to confirm — do you want a full study of *{passage}*, "
        f"or did you have a specific question about it?",
        parse_mode="Markdown"
    )
    return True


# ── Main Message Handler ──────────────────────────────────────────────────────

@dp.message()
async def handle_message(message: Message):
    if not is_authorized(message):
        return

    text = (message.text or "").strip()
    if not text:
        return

    # Resolve pending clarification first
    if pending_clarification["active"]:
        handled = await resolve_pending_clarification(message, text)
        if handled:
            return

    # Classify intent
    loop = asyncio.get_event_loop()
    classification = await loop.run_in_executor(None, classify_intent, text)

    intent = classification.get("intent", "DIALOGUE")
    passage = classification.get("passage")

    log.info(f"Intent: {intent} | Passage: {passage} | Confidence: {classification.get('confidence')}")

    if intent == "SET_PASSAGE" and passage:
        await handle_set_passage(message, passage)

    elif intent == "RUN_PHASE1":
        await handle_run_phase1(message)

    elif intent == "RUN_PHASE2":
        await handle_run_phase2(message)

    elif intent == "RUN_PHASE3":
        await handle_run_phase3(message)

    elif intent == "FETCH_SERMON":
        await handle_fetch_sermon(message)

    elif intent == "SIDE_STUDY" and passage:
        await handle_side_study(message, passage)

    elif intent == "SIDE_JOURNAL":
        await handle_side_journal(message)

    elif intent == "SAVE_STUDY":
        await handle_save_study(message)

    elif intent == "DEVOTION":
        await message.answer("📖 Generating today's devotion...", parse_mode="Markdown")
        await loop.run_in_executor(None, lambda: run_devotion(force=True))

    elif intent == "STATUS":
        await message.answer(get_status_message(), parse_mode="Markdown")

    elif intent == "CLARIFY_PASSAGE" and passage:
        await handle_clarify_passage(message, passage)

    else:
        # DIALOGUE or anything unclassified
        await handle_dialogue(message, text)


# ── Slash Command Fallbacks (still work, never required) ─────────────────────

@dp.message(Command("study"))
async def cmd_study(message: Message):
    if is_authorized(message):
        await handle_run_phase1(message)

@dp.message(Command("phase2"))
async def cmd_phase2(message: Message):
    if is_authorized(message):
        await handle_run_phase2(message)

@dp.message(Command("journal"))
async def cmd_journal(message: Message):
    if is_authorized(message):
        await handle_run_phase3(message)

@dp.message(Command("onetime"))
async def cmd_onetime(message: Message, command: CommandObject):
    if is_authorized(message) and command.args:
        await handle_side_study(message, command.args)

@dp.message(Command("status"))
async def cmd_status(message: Message):
    if is_authorized(message):
        await message.answer(get_status_message(), parse_mode="Markdown")

@dp.message(Command("start", "help"))
async def cmd_help(message: Message):
    if is_authorized(message):
        await message.answer(
            "📖 *Bible Study Agent*\n\n"
            "Just talk to me naturally:\n\n"
            "• *\"This week we're in Luke 15:1-10\"* — sets the passage\n"
            "• *\"Let's study this\"* — runs the exegetical study\n"
            "• *\"Add the sermon\"* — runs sermon analysis\n"
            "• *\"Write the journal entry\"* — synthesis, saved to KB\n"
            "• *\"Study Psalm 46 for me\"* — side study, any passage\n"
            "• *\"Synthesize that\"* — journal entry for side study\n"
            "• *\"Save this study\"* — logs side study to KB\n"
            "• *\"Give me today's devotion\"* — morning devotion\n"
            "• *\"Where are we in the study?\"* — current progress\n\n"
            "Or just ask a Bible question directly.",
            parse_mode="Markdown"
        )


# ── Entry Point ───────────────────────────────────────────────────────────────

async def main():
    log.info("Bible Study Bot starting...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
