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

from steam_library import _STEAM_ROOT_CANDIDATES

# Same conversion constant used in dota_stats_bot/steam_api.py (STEAM64_BASE).
STEAM64_BASE = 76561197960265728

# Steam's own config lives under its install ROOT, not under whichever
# library folder happens to have a given game (that's a separate concept -
# see steam_library.py) - so this reuses the same root-candidate list
# (covers flatpak/snap too) rather than the old hardcoded 2-path list,
# which missed ~/.steam/root and both packaged variants.
_CANDIDATE_PATHS = tuple(f"{root}/config/loginusers.vdf" for root in _STEAM_ROOT_CANDIDATES)

# Manual escape hatch, same pattern as steam_library_override.txt: if
# auto-detection still can't find/parse loginusers.vdf, drop the account_id
# (Steam32, not the 17-digit SteamID64) in this file, one line, no quotes.
# Checked first, before any auto-detection.
_OVERRIDE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "steam_account_override.txt")

# Each account entry: a 17-digit SteamID64 key followed by a brace-delimited
# body. Bodies in this file are flat (no nested braces), so a non-nested
# character class between the braces is sufficient.
_ACCOUNT_BLOCK_RE = re.compile(r'"(\d{17})"\s*\{([^{}]*)\}')
_MOST_RECENT_RE = re.compile(r'"MostRecent"\s*"1"', re.IGNORECASE)


def _find_loginusers_path():
    for candidate in _CANDIDATE_PATHS:
        path = os.path.expanduser(candidate)
        if os.path.isfile(path):
            return path
    return None


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
