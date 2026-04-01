"""
gemini_client.py
Unified AI client for the Bible Study Bot.

Routing:
  Daily devotions            → Claude Sonnet (primary user-facing product; no ESV copyright issues)
  Phase 3 journal synthesis  → Claude Sonnet (best reasoning, ~$0.05-0.08/call)
  Phase 1 / Phase 2          → Gemini 2.5 Flash (free tier, 1,500 req/day)
  Dialogue / intent classify → Gemini 2.5 Flash (free tier)

Fallback: if Anthropic API call fails, falls back to Gemini with a warning.
This keeps the bot operational even if API credits run out.
"""

import os
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()

# ── Configure Gemini ──────────────────────────────────────────────────────────

genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
GEMINI_MODEL = "gemini-2.5-flash"

# ── Configure Anthropic (devotions + Phase 3) ────────────────────────────────

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
ANTHROPIC_MODEL = "claude-sonnet-4-6"  # Latest Sonnet — devotions + Phase 3

try:
    import anthropic
    _anthropic_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY) if ANTHROPIC_API_KEY else None
except ImportError:
    _anthropic_client = None
    print("[gemini_client] anthropic package not installed — devotions and Phase 3 will use Gemini fallback.")


# ── KB Context Injection ──────────────────────────────────────────────────────

def load_kb_context() -> str:
    """
    Reads STYLE.md and GOALS.md from the Chief of Staff knowledge base.
    Read-only — the Bible study bot never writes to the CoS KB directly.
    Returns empty string if files not present (graceful degradation).
    """
    kb_root = os.path.expanduser("~/chief-of-staff/knowledge-base/context")
    context_parts = []

    for filename in ["STYLE.md", "GOALS.md"]:
        path = os.path.join(kb_root, filename)
        if os.path.exists(path):
            with open(path, "r") as f:
                content = f.read().strip()
            if content:
                context_parts.append(f"[{filename}]\n{content}")

    if context_parts:
        return "\n\n---\n\n".join(context_parts)
    return ""


def build_system_prompt_with_context(base_prompt: str) -> str:
    """
    Injects CoS KB context into the system prompt so outputs reflect
    Daniel's voice and vocational context. Used for devotions and Phase 3.
    """
    kb_context = load_kb_context()
    if not kb_context:
        return base_prompt
    return base_prompt + f"""

---

PERSONAL CONTEXT (from Chief of Staff knowledge base — use to inform application and tone):
{kb_context}

Use this context to ground applications in Daniel's actual vocational situation and
reasoning patterns. Do not reference this context explicitly in outputs.
"""


# ── Gemini Generation ─────────────────────────────────────────────────────────

def _gemini_generate(system_prompt: str, user_prompt: str) -> str:
    model = genai.GenerativeModel(
        model_name=GEMINI_MODEL,
        system_instruction=system_prompt
    )
    response = model.generate_content(user_prompt)
    return response.text


def _gemini_generate_with_history(
    system_prompt: str,
    history: list[dict],
    user_message: str
) -> str:
    model = genai.GenerativeModel(
        model_name=GEMINI_MODEL,
        system_instruction=system_prompt
    )
    chat = model.start_chat(history=history)
    response = chat.send_message(user_message)
    return response.text


# ── Anthropic Generation ──────────────────────────────────────────────────────

def _claude_generate(system_prompt: str, user_prompt: str) -> str:
    """Single-turn Claude Sonnet call. Used for devotions and Phase 3 synthesis."""
    if not _anthropic_client:
        raise RuntimeError("Anthropic client not available")

    message = _anthropic_client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=4096,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}]
    )
    return message.content[0].text


# ── Public Interface ──────────────────────────────────────────────────────────

def generate(
    system_prompt: str,
    user_prompt: str,
    inject_kb_context: bool = False,
    use_claude: bool = False
) -> str:
    """
    Single-turn generation.
    use_claude=True routes to Claude Sonnet (devotions and Phase 3).
    Falls back to Gemini if Claude is unavailable.
    """
    if inject_kb_context:
        system_prompt = build_system_prompt_with_context(system_prompt)

    if use_claude:
        try:
            return _claude_generate(system_prompt, user_prompt)
        except Exception as e:
            print(f"[gemini_client] Claude call failed ({e}), falling back to Gemini.")

    return _gemini_generate(system_prompt, user_prompt)


def generate_with_history(
    system_prompt: str,
    history: list[dict],
    user_message: str,
    inject_kb_context: bool = False
) -> str:
    """
    Multi-turn dialogue. Always uses Gemini (dialogue doesn't justify Claude cost).
    History format: [{"role": "user", "parts": ["..."]}, {"role": "model", "parts": ["..."]}]
    """
    if inject_kb_context:
        system_prompt = build_system_prompt_with_context(system_prompt)

    return _gemini_generate_with_history(system_prompt, history, user_message)
