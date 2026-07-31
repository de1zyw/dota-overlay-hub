"""Parses and watches Dota's server_log.txt for the latest match's roster.
Format confirmed against github.com/creepycheese/dota2-server-log's test fixture:
repeated `<slot>:[U:1:<account_id>]` tokens on a line containing DOTA_GAMEMODE.
Slot order [0,1,2,3,4,128,129,130,131,132] - first 5 Radiant, last 5 Dire."""
import os
import re
import time

_ENTRY_RE = re.compile(r"(\d+):\[U:1:(\d+)\]")
_RADIANT_SLOTS = {0, 1, 2, 3, 4}


def _parse_line(line):
    if "DOTA_GAMEMODE" not in line:
        return None
    matches = _ENTRY_RE.findall(line)
    if len(matches) != 10:
        return None

    roster = []
    for slot_str, account_id_str in matches:
        slot = int(slot_str)
        account_id = int(account_id_str)
        if slot in _RADIANT_SLOTS:
            roster.append(("radiant", slot, account_id))
        else:
            roster.append(("dire", slot - 128, account_id))
    return roster


def parse_latest_match(log_path):
    with open(log_path, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()

    for line in reversed(lines):
        roster = _parse_line(line)
        if roster:
            return roster
    return []


def watch_for_new_match(log_path, callback, poll_interval=1.0):
    last_size = os.path.getsize(log_path) if os.path.exists(log_path) else 0
    while True:
        time.sleep(poll_interval)
        if not os.path.exists(log_path):
            continue
        size = os.path.getsize(log_path)
        if size > last_size:
            last_size = size
            roster = parse_latest_match(log_path)
            if roster:
                callback(roster)
        elif size < last_size:
            last_size = size  # file truncated/rotated, resync silently
