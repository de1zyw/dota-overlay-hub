"""Persisted history of profile lookups (nickname + account_id + when),
so the hub's ИСТОРИЯ page can show past lookups without redoing OCR.
Never raises - a corrupt/missing history file is treated as empty."""
import json
import os
from datetime import datetime, timezone

HISTORY_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "profile_lookup_history.json")
MAX_ENTRIES = 100


def load_all():
    try:
        with open(HISTORY_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            return []
        return data
    except (OSError, json.JSONDecodeError):
        return []


def append(account_id, nickname):
    entries = load_all()
    entries.insert(0, {
        "account_id": account_id,
        "nickname": nickname,
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    })
    entries = entries[:MAX_ENTRIES]
    try:
        with open(HISTORY_PATH, "w", encoding="utf-8") as f:
            json.dump(entries, f, indent=2)
        return True
    except OSError:
        return False
