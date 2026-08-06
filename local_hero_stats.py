"""Reads per-hero personal-best/streak stats out of Dota's local Steam
Cloud cache file - data that doesn't exist anywhere in public OpenDota
(confirmed: OpenDota's own /players/{id}/heroes has no streak/peak
fields). Same file family as last_match_watcher.py's last_match.dat
(VBKV/binary-KeyValues), but with a repeating per-hero block structure.

Confirmed live (2026-08-06) against the real stats.dat: this is NOT the
classic binary VDF format the `vdf` PyPI package parses - that package
raised "Unknown data type 0x0b" partway through a real file, because this
VBKV variant closes objects with 0x0B instead of the classic format's
0x08. The parser below was hand-verified byte-by-byte against the real
file (consumed exactly 55935/55935 payload bytes, zero leftover) - no
external dependency needed."""
import os
import struct

from steam_library import _find_steam_root

# Confirmed via hex-dump work on both last_match.dat and stats.dat: VBKV's
# own header is 4 bytes of "VBKV" magic + 4 bytes of checksum, before the
# actual binary-KeyValues payload starts.
_VBKV_HEADER_SIZE = 8

_TYPE_OBJECT = 0x00
_TYPE_INT32 = 0x02
_TYPE_FLOAT32 = 0x03
_TYPE_UINT64 = 0x07
_TYPE_END = 0x0B


def _read_cstring(data, pos):
    end = data.index(b"\x00", pos)
    return data[pos:end].decode("utf-8", errors="replace"), end + 1


def _parse_object(data, pos):
    result = {}
    while True:
        type_byte = data[pos]
        pos += 1
        if type_byte == _TYPE_END:
            return result, pos
        key, pos = _read_cstring(data, pos)
        if type_byte == _TYPE_OBJECT:
            value, pos = _parse_object(data, pos)
        elif type_byte == _TYPE_INT32:
            value = struct.unpack_from("<i", data, pos)[0]
            pos += 4
        elif type_byte == _TYPE_FLOAT32:
            value = struct.unpack_from("<f", data, pos)[0]
            pos += 4
        elif type_byte == _TYPE_UINT64:
            value = struct.unpack_from("<Q", data, pos)[0]
            pos += 8
        else:
            # An unrecognized type tag means this parser's understanding of
            # the format is incomplete (or the file is corrupt) - bail out
            # rather than silently misreading subsequent bytes as garbage.
            raise ValueError(f"unknown type 0x{type_byte:02x} at offset {pos - 1}")
        result[key] = value


def _stats_dat_path(account_id):
    if account_id is None:
        return None
    root = _find_steam_root()
    if root is None:
        return None
    return os.path.join(root, "userdata", str(account_id), "570", "remote", "cfg", "stats.dat")


def get_hero_standings(account_id):
    """Returns {hero_id: {field_name: value, ...}, ...} - each inner dict
    has (at minimum) win_streak, best_win_streak, best_kills, best_gpm,
    best_xpm (confirmed real field names/types against the live file).
    Returns None if the file doesn't exist, can't be read, or fails to
    parse - never raises."""
    path = _stats_dat_path(account_id)
    if path is None:
        return None
    try:
        with open(path, "rb") as f:
            raw = f.read()
    except OSError:
        return None
    try:
        parsed, _ = _parse_object(raw[_VBKV_HEADER_SIZE:], 0)
        standings = parsed["Stats"]["hero_standings"]["standings"]
    except (KeyError, TypeError, ValueError, IndexError):
        return None
    result = {}
    for entry in standings.values():
        hero_id = entry.get("hero_id")
        if hero_id is not None:
            result[int(hero_id)] = entry
    return result
