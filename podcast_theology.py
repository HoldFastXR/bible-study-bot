"""podcast_theology.py — Logos drives a theological / Bible-adjacent Deep Dive.

Researches the topic with Logos's own Reformed, redemptive-historical method (CHARTER_BASE)
plus live web search, writes the episode to the shared Deep Dives episode spec (discipleship
lens instead of the ops lens), then hands the content off to the shared render/publish
pipeline in chief-of-staff (same Deep Dives feed → audio + HTML write-up in Apple Podcasts).

CLI:  python podcast_theology.py "where does heaven physically exist" [brief|standard|deep]
"""
import datetime, json, os, re, subprocess, sys, tempfile
from pathlib import Path

from system_prompts import CHARTER_BASE   # Logos's theological method

HOME = Path.home()
CLAUDE_BIN = os.path.expanduser("~/.local/bin/claude")
MODEL = os.getenv("LOGOS_PODCAST_MODEL", "sonnet")   # override for a hard topic
SPEC = HOME / "chief-of-staff" / "knowledge-base" / "context" / "podcast-episode-spec.md"
PIPELINE = HOME / "chief-of-staff" / "bot" / "podcast_generator.py"

LENS = """
You are writing ONE "Deep Dives" podcast episode on a THEOLOGICAL or Bible-adjacent topic,
driven by Logos. Apply the theological method above: broadly Reformed, high view of Scripture,
covenantal and redemptive-historical, Christ-centered (promise–fulfillment, typology), ESV
default, and never moralistic. Cross-disciplinary questions are welcome and expected (e.g.,
physics and the location of heaven): research the science/history/current scholarship with
WebSearch/WebFetch, but interpret it through that framework and be honest about what Scripture
does and does not settle — hold conviction and humility together.

The "applies to you" beat in each segment is DISCIPLESHIP, not operations — how this shapes
Daniel's walk with Christ, his thinking, and his leadership under Christ. Follow the structure,
length, and write-for-the-ear rules in the episode spec below (single narrator, sharp cold
open, 3–5 segments, so-what synthesis, no URLs read aloud).

RESEARCH FIRST with web tools and gather REAL source URLs you actually opened (scholarship,
articles) plus the Scripture references you lean on. Then output STRICT JSON ONLY as your final
message — no prose, no code fences — with keys: title, description (2–3 sentences), intro,
segments (list of {heading, summary, applies}), takeaway, sources (list of {title, url}),
script (the full spoken narration, paragraphs separated by blank lines, ear-written).
"""


def _research(prompt: str, model: str | None = None, timeout: int = 900) -> str:
    binary = CLAUDE_BIN if os.path.exists(CLAUDE_BIN) else "claude"
    scratch = HOME / ".cache" / "logos_podcast"
    scratch.mkdir(parents=True, exist_ok=True)
    mdl = model or MODEL
    print(f"[logos-pod] researching + writing with model={mdl}", flush=True)
    proc = subprocess.run(
        [binary, "-p", prompt, "--model", mdl,
         "--allowedTools", "WebSearch", "WebFetch", "--output-format", "json"],
        cwd=str(scratch), capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError(f"claude research failed (rc={proc.returncode}): {proc.stderr[:400]}")
    try:
        return json.loads(proc.stdout).get("result") or proc.stdout
    except json.JSONDecodeError:
        return proc.stdout


def _extract_json(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("no JSON object in model reply")
    return json.loads(m.group(0))


def generate(topic: str, tier: str = "standard", model: str | None = None) -> None:
    spec = SPEC.read_text()
    length = {"brief": "8–10 minutes", "standard": "15–20 minutes",
              "deep": "25–30 minutes"}.get(tier, "15–20 minutes")
    system = (CHARTER_BASE + "\n\n" + LENS + f"\n\nTarget length: {length}.\n\n"
              "EPISODE SPEC (structure / length / ear-writing):\n" + spec)
    prompt = system + f"\n\nTopic: {topic}\n\nResearch the topic, then write the episode as JSON."
    reply = _research(prompt, model=model)
    data = _extract_json(reply)
    script = data.pop("script")
    data.setdefault("topic", topic)
    data["date"] = datetime.datetime.now().strftime("%B %d, %Y")
    data["date_iso"] = datetime.datetime.now().astimezone().isoformat()
    data["model"] = f"Logos · {model or MODEL}"

    # hand off to the shared Deep Dives render/publish pipeline
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as jf:
        json.dump(data, jf); jp = jf.name
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as sf:
        sf.write(script); sp = sf.name
    print("[logos-pod] handing off to Deep Dives pipeline ...", flush=True)
    subprocess.run([sys.executable, str(PIPELINE), jp, sp], check=True)
    os.unlink(jp); os.unlink(sp)
    print("[logos-pod] done — published to the Deep Dives feed", flush=True)


if __name__ == "__main__":
    generate(sys.argv[1],
             sys.argv[2] if len(sys.argv) > 2 else "standard",
             sys.argv[3] if len(sys.argv) > 3 else None)
