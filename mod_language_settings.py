"""Persisted "-language <slot>" preference for the МОДЫ tab's install
folder (mod_manager.py).

IMPORTANT (found 2026-08-08, straight from the catalog's own site notice):
Valve has blocked arbitrary custom -language values (e.g. "123", "minify")
- only Dota's own official language folders (russian, english, etc.) are
still honored. The catalog's own current guidance is to always use
dota_russian, even to keep English Dota, since it's guaranteed to exist
and be accepted. DEFAULT_LANGUAGE reflects that, not an arbitrary custom
slot anymore. Kept open-ended (not a hard enum) since Valve's exact
allow-list isn't published anywhere authoritative enough to hard-code -
the UI surfaces a warning instead of a hard block (see mods_page.py).
load() never raises; save() rejects anything that isn't a safe folder-
name component."""
import json
import os
import re

SETTINGS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mod_language_settings.json")

DEFAULT_LANGUAGE = "russian"
# Dota's real, Steam-installed language folders - confirmed against an
# actual install (game/dota_russian, dota_schinese, dota_koreana, dota_lv
# all present) - used only to decide whether to show the "may not work,
# Valve blocked custom slots" warning, never to hard-block input.
KNOWN_OFFICIAL_LANGUAGES = frozenset({
    "russian", "english", "schinese", "tchinese", "japanese", "koreana",
    "brazilian", "bulgarian", "czech", "danish", "dutch", "finnish",
    "french", "german", "greek", "hungarian", "italian", "latam",
    "polish", "portuguese", "romanian", "spanish", "swedish", "thai",
    "turkish", "ukrainian", "vietnamese",
})
_VALID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,32}$")


def is_official(language):
    return (language or "").lower() in KNOWN_OFFICIAL_LANGUAGES


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
