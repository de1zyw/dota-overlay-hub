"""Persisted "-language <slot>" preference for the МОДЫ tab's install
folder (mod_manager.py) - lets the user point this app's mod installs at
whatever slot they already use for something else (e.g. "minify" to share
dota2-minify-bin's own folder/launch option) instead of being stuck with
this app's default ("custom"). Open-ended by design (unlike
overlay_position_settings' fixed corner set) - any string safe as a single
path component works. load() never raises; save() rejects anything that
isn't a safe folder-name component."""
import json
import os
import re

SETTINGS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mod_language_settings.json")

DEFAULT_LANGUAGE = "custom"
_VALID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,32}$")


def is_valid(language):
    return bool(_VALID_RE.match(language or ""))


def load():
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        language = data.get("language")
        if is_valid(language):
            return language
    except (OSError, json.JSONDecodeError):
        pass
    return DEFAULT_LANGUAGE


def save(language):
    if not is_valid(language):
        return False
    try:
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump({"language": language}, f, indent=2)
        return True
    except OSError:
        return False
