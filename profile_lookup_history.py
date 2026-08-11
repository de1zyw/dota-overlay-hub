"""Persisted history of profile lookups (nickname + account_id + when),
so the hub's ИСТОРИЯ page can show past lookups without redoing OCR.
Never raises - a corrupt/missing history file is treated as empty."""
import json
import os

import platform_utils
from datetime import datetime, timezone

HISTORY_PATH = os.path.join(platform_utils.data_dir(), "profile_lookup_history.json")
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


def append(account_id, nickname, match_ids):
    entries = load_all()
    entries.insert(0, {
        "account_id": account_id,
        "nickname": nickname,
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "match_ids": match_ids,
    })
    entries = entries[:MAX_ENTRIES]
    try:
        with open(HISTORY_PATH, "w", encoding="utf-8") as f:
            json.dump(entries, f, indent=2)
        return True
    except OSError:
        return False
