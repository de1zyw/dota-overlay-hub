"""Parses and watches Dota's server_log.txt for the latest match's roster
and the local client's own party grouping.

Real format (confirmed against github.com/creepycheese/dota2-server-log's
actual test log, not just its regex):
  ... (Lobby <id> DOTA_GAMEMODE_X <slot:[U:1:id]>x10) (Party <id> <slot:[U:1:id]>xN)
The Party group uses its own independent slot numbering (0-based, unrelated
to the Radiant/Dire scheme) and is present on nearly every real line - a
naive whole-line token scan (the previous implementation) would almost
always see more than 10 tokens and silently reject real matches. This
version scopes roster extraction to the (Lobby ...) group specifically.

The Party group only ever reveals the LOCAL CLIENT's own party (who you
personally queued with) - Dota's client never receives other players'
separate party groupings, so this can never be used to see whether e.g.
two enemies are partied together.

Slot order within (Lobby ...) is [0,1,2,3,4,128,129,130,131,132] - first 5
Radiant, last 5 Dire.
Note: fixtures/server_log_sample.txt is synthetic/hand-written test data
matching this confirmed real format, not a captured real log."""
import os
import re
import time

_LOBBY_RE = re.compile(r"\(Lobby\s+\d+\s+DOTA_GAMEMODE_\S+((?:\s*\d+:\[U:1:\d+\])+)\)")
_PARTY_RE = re.compile(r"\(Party\s+\d+((?:\s*\d+:\[U:1:\d+\])+)\)")
_ENTRY_RE = re.compile(r"(\d+):\[U:1:(\d+)\]")
_RADIANT_SLOTS = {0, 1, 2, 3, 4}


def _parse_line(line):
    lobby_match = _LOBBY_RE.search(line)
    if not lobby_match:
        return None, None

    lobby_tokens = _ENTRY_RE.findall(lobby_match.group(1))
    if len(lobby_tokens) != 10:
        return None, None

    roster = []
    for slot_str, account_id_str in lobby_tokens:
        slot = int(slot_str)
        account_id = int(account_id_str)
        if slot in _RADIANT_SLOTS:
            roster.append(("radiant", slot, account_id))
        else:
            roster.append(("dire", slot - 128, account_id))

    party_account_ids = set()
    party_match = _PARTY_RE.search(line)
    if party_match:
        party_tokens = _ENTRY_RE.findall(party_match.group(1))
        party_account_ids = {int(account_id_str) for _, account_id_str in party_tokens}

    return roster, party_account_ids


def parse_latest_match(log_path):
    with open(log_path, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()

    for line in reversed(lines):
        roster, party_account_ids = _parse_line(line)
        if roster:
            return roster, party_account_ids
    return [], set()


def watch_for_new_match(log_path, callback, poll_interval=1.0):
    last_size = os.path.getsize(log_path) if os.path.exists(log_path) else 0
    while True:
        time.sleep(poll_interval)
        if not os.path.exists(log_path):
            continue
        size = os.path.getsize(log_path)
        if size > last_size:
            last_size = size
            roster, party_account_ids = parse_latest_match(log_path)
            if roster:
                callback(roster, party_account_ids)
        elif size < last_size:
            last_size = size  # file truncated/rotated, resync silently
