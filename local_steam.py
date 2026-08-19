"""Detect the locally logged-in Steam account by reading Steam's own
config file, so the overlay can highlight "your own" row without the
user typing in their SteamID.

Steam writes the accounts that have ever logged in on this machine to
`config/loginusers.vdf`, in Valve's KeyValues/VDF text format:

    "users"
    {
        "76561198012345678"
        {
            "AccountName"       "somename"
            "PersonaName"       "SomeName"
            "MostRecent"        "1"
            ...
        }
    }

The outer key under "users" is the account's SteamID64. The entry with
"MostRecent" "1" is the currently/last-active local account - the one we
want, in case multiple accounts have ever logged in here.

This format is simple enough (flat key-value pairs per account, no
deeper nesting) that a couple of regexes are simpler and more robust
than pulling in a PyPI VDF-parsing dependency just for this one file.
"""
import os
import re

import platform_utils
from steam_library import _find_steam_root

# Same conversion constant used in dota_stats_bot/steam_api.py (STEAM64_BASE).
STEAM64_BASE = 76561197960265728

# Manual escape hatch, same pattern as steam_library_override.txt: if
# auto-detection still can't find/parse loginusers.vdf, drop the account_id
# (Steam32, not the 17-digit SteamID64) in this file, one line, no quotes.
# Checked first, before any auto-detection.
_OVERRIDE_FILE = os.path.join(platform_utils.data_dir(), "steam_account_override.txt")


def load_account_override():
    """Raw override text as currently saved, "" if none - same pairing with
    save_account_override() as steam_library.load_library_override() has
    with its own save function."""
    try:
        with open(_OVERRIDE_FILE, "r", encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def save_account_override(account_id):
    """Settings-page write path for the manual escape hatch documented
    above. account_id is validated as digits-only before writing (a typo'd
    non-numeric value would otherwise silently make every account_id-keyed
    feature fail later, far from where the mistake was made) - empty
    input deletes the override instead of writing an empty file, so
    auto-detection resumes. Returns True/False, never raises."""
    account_id = (account_id or "").strip()
    try:
        if not account_id:
            if os.path.isfile(_OVERRIDE_FILE):
                os.remove(_OVERRIDE_FILE)
            return True
        if not account_id.isdigit():
            return False
        with open(_OVERRIDE_FILE, "w", encoding="utf-8") as f:
            f.write(account_id)
        return True
    except OSError:
        return False


# Each account entry: a 17-digit SteamID64 key followed by a brace-delimited
# body. Bodies in this file are flat (no nested braces), so a non-nested
# character class between the braces is sufficient.
_ACCOUNT_BLOCK_RE = re.compile(r'"(\d{17})"\s*\{([^{}]*)\}')
_MOST_RECENT_RE = re.compile(r'"MostRecent"\s*"1"', re.IGNORECASE)


def _find_loginusers_path():
    # Steam's own config lives under its install ROOT, not under whichever
    # library folder happens to have a given game (that's a separate
    # concept - see steam_library.py) - reuses that module's own root
    # detection (cross-platform: Linux dotfile paths, or the Windows
    # registry/Program Files paths) rather than keeping a second,
    # independent candidate-path list that could drift out of sync with it.
    root = _find_steam_root()
    if not root:
        return None
    path = os.path.join(root, "config", "loginusers.vdf")
    return path if os.path.isfile(path) else None


def get_local_account_id():
    """Return the account_id (Steam32) of the locally logged-in Steam
    account, or None if it can't be determined.

    Degrades to None on: Steam not installed / no loginusers.vdf found,
    unreadable file, parse error, no MostRecent entry, or more than one
    MostRecent entry (genuinely ambiguous - guessing would be wrong).
    Never raises.
    """
    try:
        if os.path.isfile(_OVERRIDE_FILE):
            with open(_OVERRIDE_FILE, "r", encoding="utf-8") as f:
                override = f.read().strip()
            if override:
                try:
                    return int(override)
                except ValueError:
                    pass

        path = _find_loginusers_path()
        if not path:
            return None

        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
        except OSError:
            return None

        most_recent_ids = [
            steamid64_str
            for steamid64_str, body in _ACCOUNT_BLOCK_RE.findall(content)
            if _MOST_RECENT_RE.search(body)
        ]

        if len(most_recent_ids) != 1:
            # Zero or ambiguous multiple MostRecent entries - None is the
            # safe answer rather than guessing which account to use.
            return None

        steamid64 = int(most_recent_ids[0])
        return steamid64 - STEAM64_BASE
    except Exception:
        # Belt-and-suspenders: this function must never raise on import
        # or at call time, regardless of what's on disk.
        return None
