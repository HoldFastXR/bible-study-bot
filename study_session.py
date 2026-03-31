"""
study_session.py
Three-phase interactive Bible study workflow.

Two study pathways:
  WEEKLY (main): Tracks the current sermon series passage via state.json.
                 Phase 1 → Phase 2 (uses auto-fetched sermon) → Phase 3 (written to KB).
                 Commands: /study, /phase2, /journal

  SIDE STUDY:    One-off study of any passage, any time.
                 Does not touch weekly state. Not written to KB unless explicitly requested.
                 Command: /onetime [passage]   e.g. /onetime Psalm 46

Phase 3 routes to Claude Sonnet for highest synthesis quality.
All other phases use Gemini free tier.
"""

import os
import datetime
from pathlib import Path

from gemini_client import generate
from kb_writer import append_to_kb
from system_prompts import PHASE1_SYSTEM_PROMPT, PHASE2_SYSTEM_PROMPT, PHASE3_SYSTEM_PROMPT
from state import (
    get_active_passage,
    get_sermon_file,
    get_phase_outputs,
    set_phase_complete,
    load_state,
)


# ── Weekly Study Pathway ──────────────────────────────────────────────────────

def run_phase1() -> str:
    """Phase 1: Exegetical Study on the weekly passage."""
    passage = get_active_passage()
    if not passage:
        return "⚠️ No active passage set. Text: *This week: [passage reference]*"

    prompt = f"""
Passage: {passage}
Default Translation: ESV

Execute Phase 1 — Exegetical Study according to your instructions.

Work verse-by-verse or in natural textual units. For each unit use the sub-heading format:
[Book Chapter:Verse(s)] — [Descriptive Title]

Identify historical context, literary structure, key terms, repetition, contrasts.
Use original language only when it materially clarifies meaning.
Clearly distinguish observation from interpretive inference using the required callout format.
Do not incorporate sermon material or application in this phase.
"""

    output = generate(PHASE1_SYSTEM_PROMPT, prompt, inject_kb_context=False, use_claude=False)
    set_phase_complete(1, output)
    append_to_kb("exegetical-phase-1", passage, output)
    return output


def run_phase2() -> str:
    """Phase 2: Sermon Insights on the weekly passage. Requires Phase 1 + sermon transcript."""
    phases = get_phase_outputs()

    if phases["phase"] < 1 or not phases["phase1"]:
        return "⚠️ Phase 1 must be completed first. Send /study to begin exegetical study."

    sermon_file = get_sermon_file()
    if not sermon_file or not os.path.exists(sermon_file):
        return (
            "⚠️ No sermon transcript loaded yet.\n"
            "The sermon fetcher runs automatically Sunday evenings.\n"
            "Check /status for current state, or try again later."
        )

    with open(sermon_file, "r", encoding="utf-8") as f:
        sermon_text = f.read()

    passage = get_active_passage()

    prompt = f"""
Passage: {passage}

Phase 1 exegetical study is complete. Here is the Phase 1 output for reference:

---
{phases['phase1']}
---

Now execute Phase 2 — Sermon Insights.

Here is the sermon transcript:

---
{sermon_text}
---

Summarize the sermon's key interpretive insights in the format specified.
Scripture governs interpretation — the sermon is a second voice, not a correction.
Do not reproduce illustrations or anecdotes. Focus on interpretive and theological content.
"""

    output = generate(PHASE2_SYSTEM_PROMPT, prompt, inject_kb_context=False, use_claude=False)
    set_phase_complete(2, output)
    append_to_kb("exegetical-phase-2", passage, output)
    return output


def run_phase3() -> str:
    """Phase 3: Journal Synthesis. Routes to Claude Sonnet. Writes to KB on completion."""
    phases = get_phase_outputs()

    if phases["phase"] < 2 or not phases["phase1"] or not phases["phase2"]:
        if phases["phase"] < 1:
            return "⚠️ Phases 1 and 2 must be completed first. Send /study to begin."
        return "⚠️ Phase 2 must be completed first. Send /phase2 to run sermon analysis."

    passage = get_active_passage()

    prompt = f"""
Passage: {passage}

Both phases of the study are complete.

Phase 1 — Exegetical Study:
---
{phases['phase1']}
---

Phase 2 — Sermon Insights:
---
{phases['phase2']}
---

Execute Phase 3 — Journal Synthesis.

Produce a journal-ready entry integrating both phases. Follow the output structure exactly:
- Journal Entry Title (theologically substantive, passage-specific)
- Textual Observations (verse-based with sub-headings matching Phase 1 units)
- Theological Observations
- Interpretation Clarifications (what it teaches / what it does not teach)
- Key Cross-References
- Concise Summary (2–3 sentences)

This is distillation, not summary. Synthesize toward clarity and formation.
"""

    # Phase 3 uses Claude Sonnet for best synthesis quality
    output = generate(PHASE3_SYSTEM_PROMPT, prompt, inject_kb_context=True, use_claude=True)
    set_phase_complete(3, output)
    append_to_kb("journal-synthesis", passage, output)

    # Write complete study to KB (all phases in one file, for reference)
    _write_study_to_kb(passage, phases["phase1"], phases["phase2"], output)

    return output


# ── Side Study Pathway ────────────────────────────────────────────────────────

def run_side_study_phase1(passage: str) -> tuple[str, str]:
    """
    Phase 1 exegetical study on any passage, independent of weekly state.
    Returns (output, session_key) where session_key can be used for phase 2/3.
    """
    prompt = f"""
Passage: {passage}
Default Translation: ESV

Execute Phase 1 — Exegetical Study according to your instructions.

Work verse-by-verse or in natural textual units. For each unit use the sub-heading format:
[Book Chapter:Verse(s)] — [Descriptive Title]

Identify historical context, literary structure, key terms, repetition, contrasts.
Use original language only when it materially clarifies meaning.
Clearly distinguish observation from interpretive inference using the required callout format.
Do not incorporate sermon material or application in this phase.
"""

    output = generate(PHASE1_SYSTEM_PROMPT, prompt, inject_kb_context=False, use_claude=False)
    return output


def run_side_study_phase3(passage: str, phase1_output: str, phase2_output: str = None) -> str:
    """
    Phase 3 synthesis for a side study. Phase 2 is optional.
    Uses Claude Sonnet. Does not write to KB unless explicitly requested.
    """
    phase2_section = ""
    if phase2_output:
        phase2_section = f"""
Phase 2 — Sermon/Commentary Insights:
---
{phase2_output}
---
"""
    else:
        phase2_section = "Phase 2 (Sermon Insights): Not provided for this side study.\n"

    prompt = f"""
Passage: {passage}

Phase 1 — Exegetical Study:
---
{phase1_output}
---

{phase2_section}

Execute Phase 3 — Journal Synthesis.

Produce a journal-ready entry. Follow the output structure exactly.
If Phase 2 was not provided, synthesize from Phase 1 alone — do not fabricate sermon insights.
"""

    return generate(PHASE3_SYSTEM_PROMPT, prompt, inject_kb_context=True, use_claude=True)


# ── KB Writing ────────────────────────────────────────────────────────────────

def _write_study_to_kb(passage: str, phase1: str, phase2: str, phase3: str):
    """Writes complete weekly study to personal/bible-study/ in the CoS KB."""
    kb_dir = os.path.expanduser("~/chief-of-staff/knowledge-base/personal/bible-study")
    os.makedirs(kb_dir, exist_ok=True)

    today = datetime.date.today()
    passage_slug = passage.lower().replace(" ", "-").replace(":", "-")
    filepath = os.path.join(kb_dir, f"study-{passage_slug}.md")

    state = load_state()
    sermon_date = state.get("sermon_date", "unknown")

    with open(filepath, "w") as f:
        f.write(f"---\npassage: {passage}\nsermon_date: {sermon_date}\n")
        f.write(f"study_completed: {today.isoformat()}\ntype: bible_study_session\n---\n\n")
        f.write(f"# Bible Study — {passage}\n\n")
        f.write("---\n\n## Phase 3 — Journal Synthesis\n\n")
        f.write(phase3)
        f.write("\n\n---\n\n## Phase 1 — Exegetical Study\n\n")
        f.write(phase1)
        f.write("\n\n---\n\n## Phase 2 — Sermon Insights\n\n")
        f.write(phase2)

    print(f"[study_session] Weekly study written to KB: {filepath}")


def write_side_study_to_kb(passage: str, phase1: str, phase3: str, phase2: str = None):
    """Writes a side study to KB on explicit user request."""
    kb_dir = os.path.expanduser("~/chief-of-staff/knowledge-base/personal/bible-study")
    os.makedirs(kb_dir, exist_ok=True)

    today = datetime.date.today()
    passage_slug = passage.lower().replace(" ", "-").replace(":", "-")
    filepath = os.path.join(kb_dir, f"side-study-{passage_slug}-{today.isoformat()}.md")

    with open(filepath, "w") as f:
        f.write(f"---\npassage: {passage}\n")
        f.write(f"study_completed: {today.isoformat()}\ntype: side_study\n---\n\n")
        f.write(f"# Side Study — {passage}\n\n")
        f.write("---\n\n## Phase 3 — Journal Synthesis\n\n")
        f.write(phase3)
        f.write("\n\n---\n\n## Phase 1 — Exegetical Study\n\n")
        f.write(phase1)
        if phase2:
            f.write("\n\n---\n\n## Phase 2 — Notes\n\n")
            f.write(phase2)

    append_to_kb("side-study-synthesis", passage, phase3)
    print(f"[study_session] Side study written to KB: {filepath}")
    return filepath


# ── Status ────────────────────────────────────────────────────────────────────

def get_status_message() -> str:
    passage = get_active_passage()
    state = load_state()
    phases = get_phase_outputs()

    if not passage:
        return (
            "📋 *Study Status*\n\n"
            "No active passage set.\n"
            "Text: *This week: [passage reference]* to begin.\n\n"
            "For a one-off study: /onetime [passage]"
        )

    sermon_status = "✅ Loaded" if state.get("sermon_fetched") else "⏳ Not yet fetched"
    if state.get("sermon_date"):
        sermon_status += f" ({state['sermon_date']})"

    phase_status = {
        0: "⏳ Not started — send /study",
        1: "✅ Phase 1 done — send /phase2",
        2: "✅ Phases 1–2 done — send /journal",
        3: "✅ All phases complete",
    }.get(phases["phase"], "⏳ Not started")

    return (
        f"📋 *Study Status*\n\n"
        f"*Weekly passage:* {passage}\n"
        f"*Study progress:* {phase_status}\n"
        f"*Sermon transcript:* {sermon_status}\n\n"
        f"*Weekly commands:*\n"
        f"/study → Phase 1 (Exegetical)\n"
        f"/phase2 → Phase 2 (Sermon Insights)\n"
        f"/journal → Phase 3 (Synthesis, saved to KB)\n\n"
        f"*Side study:*\n"
        f"/onetime [passage] → Full Phase 1 on any passage\n\n"
        f"*Other:*\n"
        f"/devotion → Today's devotion\n"
        f"/help → All commands"
    )
