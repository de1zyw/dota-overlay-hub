"""Reads the numeric match_id of the player's most recent match out of
Dota's local Steam Cloud cache file - the replacement for the old
server_log.txt-based detection (lobby_watcher.py), which is confirmed dead:
modern Dota 2 (Source 2) doesn't write match rosters to any text log at
all, it talks to the Game Coordinator over an encrypted binary protocol
(confirmed 2026-08-04 against a real console.log from a real match played
that day - zero matches for the old server_log.txt regex format anywhere).

`last_match.dat` lives at
    <steam_root>/userdata/<account_id>/570/remote/cfg/last_match.dat
(570 = Dota 2's Steam AppID, "remote" = Steam Cloud's local cache - this
file is cloud-synced, not just local). It's a small Valve Binary KeyValues
(VBKV) file Dota writes via WriteSteamRemoteStorageFileAsync every time a
match is joined. Confirmed live against real data (2026-08-04): it holds
ONLY the match_id, no roster - the actual player list still has to come
from OpenDota once it has that match_id indexed (opendota_client's
fetch_match_roster).

IMPORTANT caveat, also confirmed live: the file updates close to when the
match is joined, well BEFORE OpenDota has indexed that match - OpenDota
appears to only learn about a match once Valve marks it complete, not at
start. So this detects the match_id early, but that alone doesn't make
roster data appear early. This is a post-match lookup source, not a live
draft source - see README's "Known limitations".

Deliberately a narrow byte-offset extraction (find the known field name,
read the 8 bytes right after it as a little-endian uint64) instead of a
general VBKV/binary-KeyValues parser: this file has exactly one field we
care about, this approach is confirmed against real data, and a "proper"
parser would be unverified extra complexity for no benefit here."""
import os
import struct
import time

import event_log
from steam_library import _find_steam_root

_LAST_MATCH_ID_KEY = b"last_match_id"


def _last_match_dat_path(account_id):
    if account_id is None:
        return None
    root = _find_steam_root()
    if root is None:
        return None
    return os.path.join(root, "userdata", str(account_id), "570", "remote", "cfg", "last_match.dat")


def read_last_match_id(account_id):
    """Returns the match_id (int) from last_match.dat, or None if it can't
    be found/read/parsed - file doesn't exist yet, Steam root not found,
    unexpected format, etc. Never raises."""
    path = _last_match_dat_path(account_id)
    if path is None:
        return None
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError:
        return None
    idx = data.find(_LAST_MATCH_ID_KEY)
    if idx == -1:
        return None
    idx += len(_LAST_MATCH_ID_KEY) + 1  # +1 skips the key name's own nul terminator
    val = data[idx:idx + 8]
    if len(val) != 8:
        return None
    try:
        return struct.unpack("<Q", val)[0]
    except struct.error:
        return None


def watch_for_new_match_id(account_id, callback, poll_interval=2.0):
    """Blocks forever, calling callback(match_id) once each time
    read_last_match_id() returns a value different from the last one seen.
    Mirrors lobby_watcher.watch_for_new_match's polling-loop shape so
    app.py can wire either one the same way."""
    last_id = read_last_match_id(account_id)
    event_log.log("LAST_MATCH_WATCHER_START", account_id=account_id, baseline_match_id=last_id)
    while True:
        time.sleep(poll_interval)
        try:
            current_id = read_last_match_id(account_id)
        except Exception as e:
            event_log.log("LAST_MATCH_WATCHER_ERROR", message=str(e))
            continue
        if current_id is not None and current_id != last_id:
            last_id = current_id
            event_log.log("LAST_MATCH_ID_CHANGED", match_id=current_id)
            callback(current_id)
