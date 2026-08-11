"""Persisted hotkey bindings, editable via the hub's settings page.
load() never raises - a missing/corrupt settings file just falls back to
the built-in defaults. save() never raises either - a failed write just
means the change didn't persist, reported by the caller's own UI feedback,
not a crash."""
import json
import os

import platform_utils

SETTINGS_PATH = os.path.join(platform_utils.data_dir(), "hotkey_settings.json")

DEFAULTS = {
    "toggle": "<ctrl>+<alt>+d",
    "expand": "<ctrl>+<alt>+e",
    "self_stats": "<ctrl>+<alt>+s",
    "calibrate": "<ctrl>+<alt>+r",
    "profile_lookup": "<ctrl>+<alt>+p",
    "last_match": "<ctrl>+<alt>+m",
}


def load():
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return dict(DEFAULTS)
        return {key: (data.get(key) or DEFAULTS[key]) for key in DEFAULTS}
    except (OSError, json.JSONDecodeError):
        return dict(DEFAULTS)


def save(hotkeys):
    try:
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump({key: hotkeys.get(key, DEFAULTS[key]) for key in DEFAULTS}, f, indent=2)
        return True
    except OSError:
        return False
