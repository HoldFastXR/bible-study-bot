"""
state.py
Manages bot state — active passage, study phase, sermon status.
All state lives in state.json. Simple, durable, inspectable via SSH.
"""

import json
import os
from datetime import datetime
from pathlib import Path

STATE_FILE = Path(__file__).parent / "state.json"

DEFAULT_STATE = {
    "active_passage": None,          # e.g. "Luke 14:12-24"
    "active_passage_set": None,      # ISO timestamp when passage was set
    "study_phase": 0,                # 0=not started, 1=phase1 done, 2=phase2 done
    "sermon_fetched": False,         # whether sermon transcript is loaded this week
    "sermon_date": None,             # date of fetched sermon (YYYY-MM-DD)
    "sermon_file": None,             # path to stored transcript
    "last_devotion_sent": None,      # date of last devotion (YYYY-MM-DD)
    "phase1_output": None,           # stored Phase 1 result
    "phase2_output": None,           # stored Phase 2 result
}


def load_state() -> dict:
    if STATE_FILE.exists():
        with open(STATE_FILE, "r") as f:
            state = json.load(f)
        # Merge with defaults to handle new keys added over time
        for key, value in DEFAULT_STATE.items():
            if key not in state:
                state[key] = value
        return state
    return DEFAULT_STATE.copy()


def save_state(state: dict):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def set_active_passage(passage: str):
    state = load_state()
    state["active_passage"] = passage
    state["active_passage_set"] = datetime.utcnow().isoformat()
    state["study_phase"] = 0
    state["sermon_fetched"] = False
    state["phase1_output"] = None
    state["phase2_output"] = None
    save_state(state)


def get_active_passage() -> str | None:
    return load_state().get("active_passage")


def set_sermon_fetched(sermon_date: str, sermon_file: str):
    state = load_state()
    state["sermon_fetched"] = True
    state["sermon_date"] = sermon_date
    state["sermon_file"] = sermon_file
    save_state(state)


def get_sermon_file() -> str | None:
    state = load_state()
    if state.get("sermon_fetched") and state.get("sermon_file"):
        return state["sermon_file"]
    return None


def set_phase_complete(phase: int, output: str):
    state = load_state()
    state["study_phase"] = phase
    if phase == 1:
        state["phase1_output"] = output
    elif phase == 2:
        state["phase2_output"] = output
    save_state(state)


def get_phase_outputs() -> dict:
    state = load_state()
    return {
        "phase": state.get("study_phase", 0),
        "phase1": state.get("phase1_output"),
        "phase2": state.get("phase2_output"),
    }


def set_devotion_sent(date_str: str):
    state = load_state()
    state["last_devotion_sent"] = date_str
    save_state(state)


def devotion_sent_today() -> bool:
    state = load_state()
    today = datetime.utcnow().strftime("%Y-%m-%d")
    return state.get("last_devotion_sent") == today
