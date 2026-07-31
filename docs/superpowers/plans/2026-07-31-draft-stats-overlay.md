# Dota 2 Draft Stats Overlay — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A PyQt overlay that shows, during Dota 2's draft phase, stats for all 10 lobby players (rank, total games, recent form, most-played heroes, pro-scene ban meta, best-effort live hero pick) — sourced entirely from legal, public/local data (OpenDota API + Dota's own `server_log.txt` + official GSI), no packet interception or memory reading.

**Architecture:** Independent modules behind small interfaces — stats fetching, log-file watching, GSI capture, a slot-based join between the two, and the UI — wired together in `app.py`. Every module is manually runnable/verifiable on its own with real or synthetic data; no piece requires a live Dota match to check except the final slot-numbering hypothesis.

**Tech Stack:** Python 3, PyQt6 (or PySide6 — see Task 1), `requests` (OpenDota), `pynput` (global hotkeys), stdlib `http.server` (GSI receiver), stdlib `sqlite3`/`json` as needed. No test framework — verification is manual per task (explicit user decision, no automated test suite for this project).

## Global Constraints

- No automated tests / no TDD — every task ends in a **manual verification step** (run a script, read the printed/rendered output, compare to an expected value spelled out in the task) instead of a pytest run.
- Target platform for this pass: **Linux (Arch/CachyOS), assume X11** — Wayland global-hotkey/always-on-top behavior is a known open risk, not solved here.
- Global hotkeys via **`pynput`**, never `keyboard` (requires root on Linux via evdev).
- OpenDota calls must go through the throttle/cache/retry pattern below (`MIN_REQUEST_INTERVAL = 1.05s`, `MAX_RETRIES = 4`, retry on `{429, 500, 502, 503, 504}`) — this is the same pattern already proven in `~/dota_stats_bot/opendota_api.py`; don't call `requests` directly from anywhere except `opendota_client.py`.
- `server_log.txt` slot order is `[0, 1, 2, 3, 4, 128, 129, 130, 131, 132]` — first 5 tokens on a match line are Radiant (team-relative slots 0-4), last 5 are Dire (team-relative slots 0-4 after subtracting 128). Steam IDs in the file are already Steam32 `account_id` — never convert them.
- The exact raw JSON key names Dota 2's GSI POSTs for the `draft` section are **not confirmed** (only a C# wrapper library's abstracted property names are documented, not the literal wire JSON). Do not hardcode a single assumed schema as if verified — `gsi_server.py` must capture the raw JSON for later inspection, and the "current pick" extraction is explicitly best-effort until the user supplies a real captured payload.
- Hidden/private OpenDota profiles and OpenDota network failures must degrade to a visible placeholder row — never raise/crash the overlay.
- No hero icon images in this pass — text + color only. Icon assets are a later polish pass, not a blocker.

---

## File Structure

```
dota_overlay/
├── requirements.txt
├── config.py               # Task 1 — paths, hotkeys, colors, timing constants
├── opendota_client.py       # Task 2 — PlayerStats fetch (adapted from dota_stats_bot)
├── meta_client.py           # Task 3 — pro-scene ban-rate meta stat
├── lobby_watcher.py         # Task 4 — parses/watches server_log.txt
├── gsi_server.py            # Task 5 — local HTTP receiver for Dota's GSI POSTs
├── draft_matcher.py         # Task 6 — joins lobby_watcher + gsi_server by (team, slot)
├── overlay_window.py        # Task 7 — PyQt frameless/always-on-top UI
├── hotkeys.py               # Task 8 — global show/hide + expand via pynput
├── app.py                   # Task 9 — wires everything together
├── gamestate_integration_dota_overlay.cfg  # Task 10 — GSI config for the user to install
└── fixtures/
    └── server_log_sample.txt   # Task 4 — synthetic fixture, documented as synthetic
```

---

### Task 1: Project scaffolding + config

**Files:**
- Create: `requirements.txt`
- Create: `config.py`

**Interfaces:**
- Produces: module-level constants in `config.py` — `STEAM_LIBRARY`, `SERVER_LOG_PATH`, `GSI_CFG_DIR`, `GSI_HOST`, `GSI_PORT`, `AUTO_HIDE_SECONDS`, `POLL_INTERVAL_SECONDS`, `HOTKEY_TOGGLE`, `HOTKEY_EXPAND`, `WINRATE_GREEN`, `WINRATE_RED`, `COLOR_GREEN`, `COLOR_NEUTRAL`, `COLOR_RED`, `WINDOW_MARGIN_PX`, `WINDOW_OPACITY`. Every later task imports these by name — don't rename any of them once written.

- [ ] **Step 1: Write `requirements.txt`**

```
requests==2.32.3
PyQt6==6.7.1
pynput==1.7.7
```

- [ ] **Step 2: Install dependencies**

Run: `cd /home/de1zyw/dota_overlay && pip install -r requirements.txt --break-system-packages`
Expected: all three packages install without error. If PyQt6 fails to build/install (missing system Qt libs), fall back to `PySide6==6.7.2` in requirements.txt instead and note the swap — the two have near-identical APIs and Task 7 uses only basic widgets.

- [ ] **Step 3: Write `config.py`**

```python
import os

STEAM_LIBRARY = os.path.expanduser("~/.local/share/Steam")
SERVER_LOG_PATH = os.path.join(
    STEAM_LIBRARY, "steamapps/common/dota 2 beta/game/dota/server_log.txt"
)
GSI_CFG_DIR = os.path.join(
    STEAM_LIBRARY, "steamapps/common/dota 2 beta/game/dota/cfg/gamestate_integration"
)

GSI_HOST = "127.0.0.1"
GSI_PORT = 3500

AUTO_HIDE_SECONDS = 25
POLL_INTERVAL_SECONDS = 1.0

HOTKEY_TOGGLE = "<ctrl>+<alt>+d"
HOTKEY_EXPAND = "<ctrl>+<alt>+e"

WINRATE_GREEN = 55.0
WINRATE_RED = 45.0

COLOR_GREEN = "#3ecf5e"
COLOR_NEUTRAL = "#cccccc"
COLOR_RED = "#e2574c"

WINDOW_MARGIN_PX = 20
WINDOW_OPACITY = 0.85
```

- [ ] **Step 4: Manual verification**

Run: `cd /home/de1zyw/dota_overlay && python3 -c "import config; print(config.SERVER_LOG_PATH); print(config.AUTO_HIDE_SECONDS)"`
Expected output:
```
/home/de1zyw/.local/share/Steam/steamapps/common/dota 2 beta/game/dota/server_log.txt
25
```

- [ ] **Step 5: Commit**

```bash
cd /home/de1zyw/dota_overlay
git add requirements.txt config.py
git commit -m "Add project scaffolding and config constants"
```

---

### Task 2: OpenDota player stats client

**Files:**
- Create: `opendota_client.py`

**Interfaces:**
- Consumes: nothing (standalone).
- Produces: `PlayerStats` dataclass with fields `account_id: int, nickname: str, hidden: bool, rank_tier: int|None, total_games: int, winrate: float|None, last10: str, top_heroes: list[int], dotabuff_url: str`. Function `fetch_player_stats(account_id: int) -> PlayerStats`. Later tasks (`overlay_window.py`, `app.py`) call `fetch_player_stats` and read these exact field names — don't rename any of them.

- [ ] **Step 1: Write `opendota_client.py`**

```python
"""Thin OpenDota client - throttled, cached, retrying.
Adapted from ~/dota_stats_bot/opendota_api.py, trimmed to what the overlay needs."""
import random
import threading
import time
from dataclasses import dataclass, field

import requests

BASE_URL = "https://api.opendota.com/api"
MIN_REQUEST_INTERVAL = 1.05
MAX_RETRIES = 4
RETRYABLE_STATUSES = {429, 500, 502, 503, 504}

_last_request_at = 0.0
_throttle_lock = threading.Lock()
_cache = {}
_cache_lock = threading.Lock()


class OpenDotaError(Exception):
    pass


def _throttle():
    global _last_request_at
    with _throttle_lock:
        wait = _last_request_at + MIN_REQUEST_INTERVAL - time.time()
        if wait > 0:
            time.sleep(wait)
        _last_request_at = time.time()


def _get(endpoint, params=None, timeout=(5, 15)):
    last_error = "unknown error"
    for attempt in range(MAX_RETRIES):
        _throttle()
        try:
            resp = requests.get(f"{BASE_URL}{endpoint}", params=params, timeout=timeout)
        except requests.exceptions.RequestException as e:
            last_error = str(e)
            time.sleep((2 ** attempt) + random.uniform(0, 0.5))
            continue
        if resp.status_code in RETRYABLE_STATUSES:
            last_error = f"HTTP {resp.status_code}"
            if attempt < MAX_RETRIES - 1:
                time.sleep((2 ** attempt) + random.uniform(0, 0.5))
                continue
        try:
            resp.raise_for_status()
        except requests.exceptions.RequestException as e:
            raise OpenDotaError(f"OpenDota request failed: {e}")
        return resp.json()
    raise OpenDotaError(f"OpenDota unreachable after {MAX_RETRIES} attempts ({last_error})")


def _cached_get(endpoint, params=None, ttl=30):
    key = (endpoint, tuple(sorted((params or {}).items())))
    with _cache_lock:
        entry = _cache.get(key)
        if entry and entry[0] > time.time():
            return entry[1]
    data = _get(endpoint, params)
    with _cache_lock:
        _cache[key] = (time.time() + ttl, data)
    return data


@dataclass
class PlayerStats:
    account_id: int
    nickname: str
    hidden: bool
    rank_tier: int = None
    total_games: int = 0
    winrate: float = None
    last10: str = ""
    top_heroes: list = field(default_factory=list)
    dotabuff_url: str = ""


def fetch_player_stats(account_id):
    dotabuff_url = f"https://www.dotabuff.com/players/{account_id}"

    try:
        profile = _cached_get(f"/players/{account_id}", ttl=30)
    except OpenDotaError:
        return PlayerStats(account_id=account_id, nickname=f"[{account_id}]", hidden=True,
                            dotabuff_url=dotabuff_url)

    profile_info = profile.get("profile") or {}
    nickname = profile_info.get("personaname") or f"[{account_id}]"

    try:
        wl = _cached_get(f"/players/{account_id}/wl", ttl=30)
    except OpenDotaError:
        wl = {}
    wins, losses = wl.get("win", 0), wl.get("lose", 0)
    total_games = wins + losses
    winrate = (wins / total_games * 100) if total_games else None
    hidden = total_games == 0 and not profile_info.get("personaname")

    try:
        recent = _cached_get(f"/players/{account_id}/recentMatches", ttl=20) or []
    except OpenDotaError:
        recent = []
    last10 = "".join(
        "W" if m.get("radiant_win") == (m.get("player_slot", 0) < 128) else "L"
        for m in recent[:10]
    )

    try:
        heroes = _cached_get(f"/players/{account_id}/heroes", ttl=60) or []
    except OpenDotaError:
        heroes = []
    top_heroes = [h["hero_id"] for h in heroes if h.get("games", 0) > 0][:3]

    return PlayerStats(
        account_id=account_id, nickname=nickname, hidden=hidden,
        rank_tier=profile.get("rank_tier"), total_games=total_games, winrate=winrate,
        last10=last10, top_heroes=top_heroes, dotabuff_url=dotabuff_url,
    )
```

- [ ] **Step 2: Manual verification against a real, known account**

Run:
```bash
cd /home/de1zyw/dota_overlay
python3 -c "
from opendota_client import fetch_player_stats
s = fetch_player_stats(111620041)
print(s)
"
```
Expected: a `PlayerStats(...)` line prints with `hidden=False`, a real `nickname` (not `[111620041]`), `total_games` > 0, `winrate` a float between 0-100, `last10` a string of `W`/`L` characters, `top_heroes` a non-empty list of ints. (This account is `sosla`, already used as the working example in `dota_stats_bot/README.md`.)

- [ ] **Step 3: Manual verification of the hidden-profile path**

Run:
```bash
cd /home/de1zyw/dota_overlay
python3 -c "
from opendota_client import fetch_player_stats
s = fetch_player_stats(1)
print(s)
"
```
Expected: does not raise. Prints a `PlayerStats` with `hidden=True` or `total_games=0` — account_id `1` is not a real populated profile, so this exercises the "no data" path without needing a network failure to simulate it.

- [ ] **Step 4: Commit**

```bash
cd /home/de1zyw/dota_overlay
git add opendota_client.py
git commit -m "Add OpenDota player stats client"
```

---

### Task 3: Meta ban-rate client

**Files:**
- Create: `meta_client.py`

**Interfaces:**
- Consumes: nothing (standalone).
- Produces: `fetch_top_banned_heroes(limit: int = 10) -> list[tuple[str, int]]` — list of `(localized_name, pro_ban_count)` sorted descending by `pro_ban_count`. `overlay_window.py` (Task 7) calls this for the "Best Bans" panel.

- [ ] **Step 1: Write `meta_client.py`**

```python
"""Aggregate 'most banned heroes' meta stat.
NOTE: OpenDota's /heroStats only tracks `pro_ban` (professional matches) -
there is no public-bracket ban field. This shows pro-scene ban rates,
not "your MMR bracket this week"."""
from opendota_client import _cached_get


def fetch_top_banned_heroes(limit=10):
    heroes = _cached_get("/heroStats", ttl=3600) or []
    ranked = sorted(heroes, key=lambda h: h.get("pro_ban", 0), reverse=True)
    return [(h["localized_name"], h.get("pro_ban", 0)) for h in ranked[:limit]]
```

- [ ] **Step 2: Manual verification**

Run:
```bash
cd /home/de1zyw/dota_overlay
python3 -c "
from meta_client import fetch_top_banned_heroes
for name, bans in fetch_top_banned_heroes(5):
    print(name, bans)
"
```
Expected: 5 lines print, each `<hero name> <integer>`, sorted with the largest ban count first (no zeros at the top).

- [ ] **Step 3: Commit**

```bash
cd /home/de1zyw/dota_overlay
git add meta_client.py
git commit -m "Add pro-scene ban-rate meta client"
```

---

### Task 4: server_log.txt parser and watcher

**Files:**
- Create: `lobby_watcher.py`
- Create: `fixtures/server_log_sample.txt`

**Interfaces:**
- Consumes: nothing (standalone).
- Produces: `parse_latest_match(log_path: str) -> list[tuple[str, int, int]]` returning `(team, team_slot, account_id)` tuples, `team` is the literal string `"radiant"` or `"dire"`, `team_slot` is `0-4`. Also `watch_for_new_match(log_path: str, callback: Callable[[list], None], poll_interval: float)` — polls file size, calls `callback` with the same tuple list whenever the file grows. `app.py` (Task 9) uses `watch_for_new_match`; `draft_matcher.py` (Task 6) consumes the tuple list shape from `parse_latest_match`.

- [ ] **Step 1: Write the synthetic fixture**

This fixture is **hand-written to match the confirmed format** from the reference parser
(github.com/creepycheese/dota2-server-log: repeated `<slot>:[U:1:<account_id>]` tokens on a
line containing `DOTA_GAMEMODE`) — it is not a captured real file. Replace it with a real one
once the user sends one.

`fixtures/server_log_sample.txt`:
```
[2026-07-20 18:02:11] Connecting to matchmaking server...
[2026-07-20 18:02:44] Match found. Lobby type: DOTA_GAMEMODE_ALLPICK Match ID: 7777000111
0:[U:1:111620041] 1:[U:1:222222222] 2:[U:1:333333333] 3:[U:1:444444444] 4:[U:1:555555555] 128:[U:1:666666666] 129:[U:1:777777777] 130:[U:1:888888888] 131:[U:1:999999999] 132:[U:1:101010101]
[2026-07-20 18:44:09] Match ended.
```

- [ ] **Step 2: Write `lobby_watcher.py`**

```python
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
```

- [ ] **Step 3: Manual verification of `parse_latest_match`**

Run:
```bash
cd /home/de1zyw/dota_overlay
python3 -c "
from lobby_watcher import parse_latest_match
for entry in parse_latest_match('fixtures/server_log_sample.txt'):
    print(entry)
"
```
Expected output (order matches the fixture's slot order):
```
('radiant', 0, 111620041)
('radiant', 1, 222222222)
('radiant', 2, 333333333)
('radiant', 3, 444444444)
('radiant', 4, 555555555)
('dire', 0, 666666666)
('dire', 1, 777777777)
('dire', 2, 888888888)
('dire', 3, 999999999)
('dire', 4, 101010101)
```

- [ ] **Step 4: Manual verification of `watch_for_new_match`**

Run in one terminal:
```bash
cd /home/de1zyw/dota_overlay
cp fixtures/server_log_sample.txt /tmp/watch_test.txt
python3 -c "
from lobby_watcher import watch_for_new_match
watch_for_new_match('/tmp/watch_test.txt', lambda roster: print('NEW MATCH:', roster), poll_interval=0.5)
"
```
In a second terminal, append a new match block to trigger it:
```bash
cat >> /tmp/watch_test.txt << 'EOF'
[2026-07-21 10:00:00] Match found. Lobby type: DOTA_GAMEMODE_ALLPICK Match ID: 7777000222
0:[U:1:1] 1:[U:1:2] 2:[U:1:3] 3:[U:1:4] 4:[U:1:5] 128:[U:1:6] 129:[U:1:7] 130:[U:1:8] 131:[U:1:9] 132:[U:1:10]
EOF
```
Expected: within ~0.5s, the first terminal prints `NEW MATCH:` followed by 10 tuples with account IDs `1` through `10`. Stop the watcher with Ctrl+C.

- [ ] **Step 5: Commit**

```bash
cd /home/de1zyw/dota_overlay
git add lobby_watcher.py fixtures/server_log_sample.txt
git commit -m "Add server_log.txt parser and file watcher"
```

---

### Task 5: GSI capture server

**Files:**
- Create: `gsi_server.py`

**Interfaces:**
- Consumes: `config.GSI_HOST`, `config.GSI_PORT`.
- Produces: `GSIServer` class with `.start()`, `.stop()`, `.latest_raw` (most recent parsed JSON body, or `None`), and `.captures_path` (path to the JSONL capture log). `app.py` (Task 9) and `draft_matcher.py` (Task 6) read `.latest_raw`.

- [ ] **Step 1: Write `gsi_server.py`**

```python
"""Local HTTP server that receives Dota 2's Game State Integration POSTs.

IMPORTANT: the exact raw JSON key names Dota uses for the 'draft' section
are NOT confirmed from documentation (only a C# wrapper library's abstracted
property names are known publicly, not the literal wire format). This server
does not assume a schema - it captures every payload verbatim to a JSONL file
so the real shape can be inspected once a live match is played with GSI
enabled. `latest_raw` exposes the full parsed JSON for draft_matcher.py to
attempt a best-effort read from.
"""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            self.send_response(400)
            self.end_headers()
            return

        self.server.gsi_server._on_payload(data)
        self.send_response(200)
        self.end_headers()

    def log_message(self, fmt, *args):
        pass  # silence default stderr request logging


class GSIServer:
    def __init__(self, host, port, captures_path="gsi_captures.jsonl"):
        self.host = host
        self.port = port
        self.captures_path = captures_path
        self.latest_raw = None
        self._lock = threading.Lock()
        self._httpd = None
        self._thread = None

    def _on_payload(self, data):
        with self._lock:
            self.latest_raw = data
        with open(self.captures_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(data) + "\n")

    def start(self):
        self._httpd = HTTPServer((self.host, self.port), _Handler)
        self._httpd.gsi_server = self
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()

    def stop(self):
        if self._httpd:
            self._httpd.shutdown()
            self._httpd.server_close()
```

- [ ] **Step 2: Manual verification with a simulated POST**

Run in one terminal:
```bash
cd /home/de1zyw/dota_overlay
python3 -c "
import time
from gsi_server import GSIServer
import config

srv = GSIServer(config.GSI_HOST, config.GSI_PORT, captures_path='/tmp/gsi_test.jsonl')
srv.start()
print('listening on', config.GSI_HOST, config.GSI_PORT)
time.sleep(30)
print('latest_raw:', srv.latest_raw)
srv.stop()
"
```
In a second terminal, within those 30 seconds:
```bash
curl -s -X POST http://127.0.0.1:3500/ -H "Content-Type: application/json" \
  -d '{"draft": {"activeteam": 2, "team2": {"pick0_id": 1}, "team3": {"pick0_id": 2}}}'
```
Expected: the first terminal prints `latest_raw: {'draft': {'activeteam': 2, 'team2': {'pick0_id': 1}, 'team3': {'pick0_id': 2}}}`, and `/tmp/gsi_test.jsonl` contains that same JSON as one line (check with `cat /tmp/gsi_test.jsonl`).

- [ ] **Step 3: Commit**

```bash
cd /home/de1zyw/dota_overlay
git add gsi_server.py
git commit -m "Add GSI capture server"
```

---

### Task 6: Draft matcher (slot-based join)

**Files:**
- Create: `draft_matcher.py`

**Interfaces:**
- Consumes: roster shape from `lobby_watcher.parse_latest_match` (`list[tuple[str, int, int]]`, i.e. `(team, team_slot, account_id)`); raw GSI JSON shape from `gsi_server.GSIServer.latest_raw`.
- Produces: `match_current_picks(roster: list, gsi_raw: dict | None) -> dict[int, int | None]` — maps `account_id -> hero_id` (or `None` if unresolved for that account). `overlay_window.py` (Task 7) calls this to fill the "Current" column.

- [ ] **Step 1: Write `draft_matcher.py`**

```python
"""Joins server_log.txt's (team, slot, account_id) roster with GSI's
(team, slot) -> hero_id draft data, by (team, slot).

The GSI extraction below is a BEST-EFFORT GUESS at the real key names
(team2/team3 for Radiant/Dire, pick<N>_id for team-relative slot N) - this
is NOT confirmed against a real captured payload. If it doesn't match once
real data is available, only `_extract_picks_from_gsi` needs to change;
everything else in this module (the join itself) is independent of that
guess and stays correct regardless.
"""

_TEAM_KEY = {"radiant": "team2", "dire": "team3"}


def _extract_picks_from_gsi(gsi_raw):
    """Returns {(team, team_slot): hero_id}, best-effort. Empty dict if the
    payload doesn't look like what we expect - never raises."""
    picks = {}
    if not gsi_raw:
        return picks

    draft = gsi_raw.get("draft")
    if not isinstance(draft, dict):
        return picks

    for team, team_key in _TEAM_KEY.items():
        team_data = draft.get(team_key)
        if not isinstance(team_data, dict):
            continue
        for slot in range(5):
            hero_id = team_data.get(f"pick{slot}_id")
            if hero_id:
                picks[(team, slot)] = hero_id
    return picks


def match_current_picks(roster, gsi_raw):
    picks_by_slot = _extract_picks_from_gsi(gsi_raw)
    result = {}
    for team, team_slot, account_id in roster:
        result[account_id] = picks_by_slot.get((team, team_slot))
    return result
```

- [ ] **Step 2: Manual verification with synthetic inputs**

Run:
```bash
cd /home/de1zyw/dota_overlay
python3 -c "
from draft_matcher import match_current_picks

roster = [
    ('radiant', 0, 111620041), ('radiant', 1, 222222222),
    ('dire', 0, 666666666), ('dire', 1, 777777777),
]
gsi_raw = {'draft': {'team2': {'pick0_id': 1}, 'team3': {'pick0_id': 2}}}

result = match_current_picks(roster, gsi_raw)
print(result)
"
```
Expected: `{111620041: 1, 222222222: None, 666666666: 2, 777777777: None}` — confirms slot 0 on each side resolves to the right account_id, unmatched slots come back `None` rather than raising.

- [ ] **Step 3: Manual verification of the no-GSI-data path**

Run:
```bash
cd /home/de1zyw/dota_overlay
python3 -c "
from draft_matcher import match_current_picks
roster = [('radiant', 0, 111620041)]
print(match_current_picks(roster, None))
print(match_current_picks(roster, {'unexpected': 'shape'}))
"
```
Expected: both lines print `{111620041: None}` — no exception, regardless of missing or malformed GSI data.

- [ ] **Step 4: Commit**

```bash
cd /home/de1zyw/dota_overlay
git add draft_matcher.py
git commit -m "Add best-effort draft matcher joining server_log and GSI by slot"
```

---

### Task 7: Overlay window (PyQt UI)

**Files:**
- Create: `overlay_window.py`

**Interfaces:**
- Consumes: `opendota_client.PlayerStats` (Task 2), `dict[int, int|None]` current-picks map (Task 6 shape), `meta_client.fetch_top_banned_heroes` (Task 3), `config` constants (Task 1).
- Produces: `OverlayWindow(QWidget)` with methods `.render_lobby(radiant: list[PlayerStats], dire: list[PlayerStats], current_picks: dict, banned_heroes: list[tuple[str,int]])`, `.show_overlay()`, `.hide_overlay()`, `.toggle_expanded()`. `app.py` (Task 9) and `hotkeys.py` (Task 8) call these methods by name.

- [ ] **Step 1: Write `overlay_window.py`**

```python
"""Frameless, always-on-top, translucent overlay window.
Teams stacked top-to-bottom, one row per player. Extra stats collapse
behind `.toggle_expanded()`. No hero icon images in this pass - text + color."""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

import config


def _winrate_color(winrate):
    if winrate is None:
        return config.COLOR_NEUTRAL
    if winrate >= config.WINRATE_GREEN:
        return config.COLOR_GREEN
    if winrate <= config.WINRATE_RED:
        return config.COLOR_RED
    return config.COLOR_NEUTRAL


def _player_row_text(stats, hero_id, expanded):
    if stats.hidden:
        return f"{stats.nickname} — профиль скрыт"

    winrate_str = f"{stats.winrate:.0f}%" if stats.winrate is not None else "н/д"
    current = f" | пик: {hero_id}" if hero_id else ""
    base = f"{stats.nickname} | WR {winrate_str} | {stats.last10}{current}"
    if expanded:
        base += f" | игр: {stats.total_games} | топ: {stats.top_heroes} | {stats.dotabuff_url}"
    return base


class OverlayWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowOpacity(config.WINDOW_OPACITY)

        self._expanded = False
        self._layout = QVBoxLayout(self)
        self.setLayout(self._layout)
        self.move(config.WINDOW_MARGIN_PX, config.WINDOW_MARGIN_PX)

    def _clear_layout(self):
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

    def render_lobby(self, radiant, dire, current_picks, banned_heroes):
        self._clear_layout()

        header = QLabel("RADIANT")
        header.setStyleSheet("color: white; font-weight: bold;")
        self._layout.addWidget(header)
        for stats in radiant:
            hero_id = current_picks.get(stats.account_id)
            label = QLabel(_player_row_text(stats, hero_id, self._expanded))
            label.setStyleSheet(f"color: {_winrate_color(stats.winrate)};")
            self._layout.addWidget(label)

        header = QLabel("DIRE")
        header.setStyleSheet("color: white; font-weight: bold;")
        self._layout.addWidget(header)
        for stats in dire:
            hero_id = current_picks.get(stats.account_id)
            label = QLabel(_player_row_text(stats, hero_id, self._expanded))
            label.setStyleSheet(f"color: {_winrate_color(stats.winrate)};")
            self._layout.addWidget(label)

        bans_header = QLabel("BEST BANS (pro scene)")
        bans_header.setStyleSheet("color: white; font-weight: bold;")
        self._layout.addWidget(bans_header)
        for name, count in banned_heroes:
            self._layout.addWidget(QLabel(f"{name}: {count}"))

        self.adjustSize()

    def show_overlay(self):
        self.show()

    def hide_overlay(self):
        self.hide()

    def toggle_expanded(self):
        self._expanded = not self._expanded


if __name__ == "__main__":
    import sys

    from meta_client import fetch_top_banned_heroes
    from opendota_client import fetch_player_stats

    app = QApplication(sys.argv)
    window = OverlayWindow()

    radiant = [fetch_player_stats(111620041)]
    dire = []
    window.render_lobby(radiant, dire, {111620041: None}, fetch_top_banned_heroes(3))
    window.show_overlay()

    sys.exit(app.exec())
```

- [ ] **Step 2: Manual verification**

Run: `cd /home/de1zyw/dota_overlay && python3 overlay_window.py`
Expected: a small frameless, translucent, always-on-top window appears in the top-left corner showing a "RADIANT" row with the real nickname/winrate/last10 for account `111620041` (green/red/gray text depending on their winrate), an empty "DIRE" section, and a "BEST BANS (pro scene)" list with 3 real hero names and ban counts. Close the window (or Ctrl+C in the terminal) to exit.

- [ ] **Step 3: Commit**

```bash
cd /home/de1zyw/dota_overlay
git add overlay_window.py
git commit -m "Add PyQt overlay window"
```

---

### Task 8: Global hotkeys

**Files:**
- Create: `hotkeys.py`

**Interfaces:**
- Consumes: `config.HOTKEY_TOGGLE`, `config.HOTKEY_EXPAND`.
- Produces: `HotkeyListener(on_toggle: Callable[[], None], on_expand: Callable[[], None])` with `.start()` / `.stop()`. `app.py` (Task 9) constructs this with `overlay.toggle_visibility` and `overlay.toggle_expanded`-wrapping callbacks.

- [ ] **Step 1: Write `hotkeys.py`**

```python
"""Global show/hide and expand/collapse hotkeys via pynput.
pynput, not `keyboard` - `keyboard` needs root on Linux (evdev access)."""
from pynput import keyboard

import config


class HotkeyListener:
    def __init__(self, on_toggle, on_expand):
        self._listener = keyboard.GlobalHotKeys({
            config.HOTKEY_TOGGLE: on_toggle,
            config.HOTKEY_EXPAND: on_expand,
        })

    def start(self):
        self._listener.start()

    def stop(self):
        self._listener.stop()
```

- [ ] **Step 2: Manual verification**

Run:
```bash
cd /home/de1zyw/dota_overlay
python3 -c "
import time
from hotkeys import HotkeyListener

listener = HotkeyListener(
    on_toggle=lambda: print('TOGGLE pressed'),
    on_expand=lambda: print('EXPAND pressed'),
)
listener.start()
print('Press Ctrl+Alt+D or Ctrl+Alt+E within 15 seconds...')
time.sleep(15)
listener.stop()
"
```
Expected: pressing Ctrl+Alt+D prints `TOGGLE pressed`, pressing Ctrl+Alt+E prints `EXPAND pressed`, both while focus is on a *different* window (proving it's global, not app-local). If nothing prints, check whether the desktop session is X11 (`echo $XDG_SESSION_TYPE`) — Wayland is a known open risk per the Global Constraints section, not solved in this task.

- [ ] **Step 3: Commit**

```bash
cd /home/de1zyw/dota_overlay
git add hotkeys.py
git commit -m "Add global hotkey listener via pynput"
```

---

### Task 9: Wire it all together

**Files:**
- Create: `app.py`

**Interfaces:**
- Consumes: everything from Tasks 1-8 by their established names.
- Produces: a runnable entry point (`python3 app.py`). No further consumers — this is the top of the dependency graph.

- [ ] **Step 1: Write `app.py`**

```python
"""Wires lobby_watcher -> opendota_client (threaded) -> overlay_window,
with GSI-based best-effort current-pick resolution and auto-hide."""
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication

import config
from draft_matcher import match_current_picks
from gsi_server import GSIServer
from hotkeys import HotkeyListener
from lobby_watcher import watch_for_new_match
from meta_client import fetch_top_banned_heroes
from opendota_client import fetch_player_stats
from overlay_window import OverlayWindow


class OverlayApp:
    def __init__(self):
        self.qt_app = QApplication(sys.argv)
        self.window = OverlayWindow()
        self.gsi = GSIServer(config.GSI_HOST, config.GSI_PORT)
        self.executor = ThreadPoolExecutor(max_workers=10)
        self.hide_timer = QTimer()
        self.hide_timer.setSingleShot(True)
        self.hide_timer.timeout.connect(self.window.hide_overlay)

        self.hotkeys = HotkeyListener(
            on_toggle=self._toggle_visibility,
            on_expand=self._expand,
        )

    def _toggle_visibility(self):
        if self.window.isVisible():
            self.window.hide_overlay()
        else:
            self.window.show_overlay()

    def _expand(self):
        self.window.toggle_expanded()

    def on_new_match(self, roster):
        account_ids = [account_id for _, _, account_id in roster]
        stats_by_id = dict(zip(account_ids, self.executor.map(fetch_player_stats, account_ids)))

        radiant = [stats_by_id[aid] for team, _, aid in roster if team == "radiant"]
        dire = [stats_by_id[aid] for team, _, aid in roster if team == "dire"]
        current_picks = match_current_picks(roster, self.gsi.latest_raw)
        banned_heroes = fetch_top_banned_heroes(10)

        self.window.render_lobby(radiant, dire, current_picks, banned_heroes)
        self.window.show_overlay()
        self.hide_timer.start(config.AUTO_HIDE_SECONDS * 1000)

    def run(self):
        self.gsi.start()
        self.hotkeys.start()

        watcher_thread = threading.Thread(
            target=watch_for_new_match,
            args=(config.SERVER_LOG_PATH, self.on_new_match, config.POLL_INTERVAL_SECONDS),
            daemon=True,
        )
        watcher_thread.start()

        sys.exit(self.qt_app.exec())


if __name__ == "__main__":
    OverlayApp().run()
```

- [ ] **Step 2: Manual end-to-end verification (no live Dota needed)**

Run in one terminal:
```bash
cd /home/de1zyw/dota_overlay
cp fixtures/server_log_sample.txt /tmp/app_test_log.txt
python3 -c "
import config
config.SERVER_LOG_PATH = '/tmp/app_test_log.txt'
from app import OverlayApp
OverlayApp().run()
"
```
In a second terminal, trigger a "new match" by appending a fresh match block (reuse the block from Task 4 Step 4, or the fixture's own block again with a different Match ID so the file genuinely grows):
```bash
cat /home/de1zyw/dota_overlay/fixtures/server_log_sample.txt | tail -1 | sed 's/7777000111/7777000999/' >> /tmp/app_test_log.txt
```
Expected: within ~1-2 seconds, the overlay window appears showing real OpenDota stats for account `111620041` (Radiant row 1) plus placeholder/"н/д" rows for the other 9 synthetic IDs (they aren't real accounts, so expect `hidden`/no-data rows for those — that's correct behavior, not a bug), and the "BEST BANS" panel populated. Press Ctrl+Alt+D to confirm it hides/shows on demand. Wait `config.AUTO_HIDE_SECONDS` (25s) without touching anything and confirm it auto-hides.

- [ ] **Step 3: Commit**

```bash
cd /home/de1zyw/dota_overlay
git add app.py
git commit -m "Wire overlay app: lobby watcher, stats fetch, GSI, hotkeys, auto-hide"
```

---

### Task 10: GSI config file for live calibration

**Files:**
- Create: `gamestate_integration_dota_overlay.cfg`

**Interfaces:**
- Consumes: `config.GSI_HOST`, `config.GSI_PORT` values (hardcode the actual current values from Task 1 into this file's `uri`, don't reference the Python module — this file is consumed by Dota 2, not Python).
- Produces: nothing further downstream — this is what the user installs into their Dota client to make live calibration (Task 5/6's real-payload check) possible.

- [ ] **Step 1: Write the GSI config**

`gamestate_integration_dota_overlay.cfg`:
```
"dota_overlay Configuration"
{
  "uri" "http://127.0.0.1:3500/"
  "timeout" "5.0"
  "buffer" "0.1"
  "throttle" "0.1"
  "heartbeat" "30.0"
  "data"
  {
    "provider" "1"
    "player" "1"
    "hero" "1"
    "draft" "1"
  }
}
```

- [ ] **Step 2: Manual install + capture instructions**

Run:
```bash
mkdir -p "/home/de1zyw/.local/share/Steam/steamapps/common/dota 2 beta/game/dota/cfg/gamestate_integration"
cp /home/de1zyw/dota_overlay/gamestate_integration_dota_overlay.cfg \
   "/home/de1zyw/.local/share/Steam/steamapps/common/dota 2 beta/game/dota/cfg/gamestate_integration/"
```
Expected: file copies without error (create the directory first if Dota's `cfg` folder doesn't have a `gamestate_integration` subfolder yet — that's normal, GSI is opt-in). Note for the user: this path is the Fedora-side path from earlier memory; if Dota is actually launched from the Arch/CachyOS side, install into that OS's equivalent Steam library path instead.

When you (the user) next play a real match with this installed: run `app.py` (Task 9) beforehand so the GSI server is listening, play through the draft, then send back `/home/de1zyw/dota_overlay/gsi_captures.jsonl` (created automatically by `gsi_server.py`) and the real `server_log.txt` from that same session. That's the exact input needed to fix `_extract_picks_from_gsi` in `draft_matcher.py` for real, and to replace the synthetic fixture in `fixtures/server_log_sample.txt`.

- [ ] **Step 3: Commit**

```bash
cd /home/de1zyw/dota_overlay
git add gamestate_integration_dota_overlay.cfg
git commit -m "Add GSI config file for live calibration"
```

---

## Phase 2: Visual polish (icons + dark gradient theme)

Added after the app was working end-to-end and user-tested. Goal: replace the plain text-only rows with real hero/rank icons and a nicer dark, translucent, softly-gradient-accented look — inspired by a user-supplied reference palette (dark background, soft blurred color glows in pink/blue/purple), adapted for a small always-on-top overlay (darker/more transparent than the reference, which was a full-opacity marketing card).

**Confirmed working, no-auth-needed image sources (verified live via curl):**
- Hero icons: `https://cdn.cloudflare.steamstatic.com/apps/dota2/images/dota_react/heroes/icons/<name>.png` (32x32, direct 200, no redirect) — `<name>` is OpenDota's `/heroes` endpoint's `name` field with the `npc_dota_hero_` prefix stripped (e.g. `npc_dota_hero_antimage` → `antimage`).
- Hero full portraits: `https://cdn.cloudflare.steamstatic.com/apps/dota2/images/dota_react/heroes/<name>.png` (256x144, needs redirect-follow — `requests` follows redirects by default, no special handling needed).
- Rank icons: `https://www.opendota.com/assets/images/dota2/rank_icons/rank_icon_<tier>_<stars>.png` for tier 1-7 with stars 1-5, and `rank_icon_<tier>.png` (no stars suffix) works for all tiers including 8 (Immortal, which has no meaningful star count) — verified all combinations return 200.

**Palette (from user-supplied reference, darkened/desaturated for an overlay context, not a full-opacity marketing card):** pink `#FF9CE3`, blue `#7DD3FC`, purple `#B388FF`, on a near-black translucent base — used as soft, low-opacity accent glows/borders, not solid fills (the overlay must stay readable over gameplay).

### Task 11: Asset fetch/cache module

**Files:**
- Create: `assets.py`
- Create: `.assets_cache/` (git-ignored — add `.assets_cache/` to `.gitignore`)

**Interfaces:**
- Consumes: nothing beyond `requests` (already a dependency) and stdlib `os`/`hashlib`.
- Produces: `get_hero_icon_path(hero_id: int) -> str | None`, `get_rank_icon_path(rank_tier: int | None) -> str | None` — both return a local filesystem path to a cached PNG (downloading + caching to `.assets_cache/` on first call for that id/tier), or `None` if the download fails (never raise — icon-less rendering must still work). `overlay_window.py` (Task 12) calls these and loads the returned path into a `QPixmap`.

- [ ] **Step 1: Write `assets.py`**

```python
"""Fetches and locally caches hero/rank icon images from public, no-auth-needed
CDN URLs (Steam's static CDN for heroes, OpenDota's own asset host for ranks).
Never raises - a failed download just means no icon for that row, not a crash."""
import os

import requests

from opendota_client import _cached_get

CACHE_DIR = os.path.join(os.path.dirname(__file__), ".assets_cache")
HERO_ICON_BASE = "https://cdn.cloudflare.steamstatic.com/apps/dota2/images/dota_react/heroes/icons"
RANK_ICON_BASE = "https://www.opendota.com/assets/images/dota2/rank_icons"

os.makedirs(CACHE_DIR, exist_ok=True)

_hero_internal_names = None


def _get_hero_internal_name(hero_id):
    global _hero_internal_names
    if _hero_internal_names is None:
        heroes = _cached_get("/heroes", ttl=3600 * 24) or []
        _hero_internal_names = {
            h["id"]: h["name"].removeprefix("npc_dota_hero_") for h in heroes
        }
    return _hero_internal_names.get(hero_id)


def _download(url, dest_path):
    if os.path.exists(dest_path):
        return dest_path
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
    except requests.exceptions.RequestException:
        return None
    with open(dest_path, "wb") as f:
        f.write(resp.content)
    return dest_path


def get_hero_icon_path(hero_id):
    if not hero_id:
        return None
    name = _get_hero_internal_name(hero_id)
    if not name:
        return None
    dest = os.path.join(CACHE_DIR, f"hero_icon_{hero_id}.png")
    return _download(f"{HERO_ICON_BASE}/{name}.png", dest)


def get_rank_icon_path(rank_tier):
    if not rank_tier:
        return None
    tier = rank_tier // 10
    dest = os.path.join(CACHE_DIR, f"rank_icon_{tier}.png")
    return _download(f"{RANK_ICON_BASE}/rank_icon_{tier}.png", dest)
```

- [ ] **Step 2: Add cache dir to .gitignore**

Add a line `.assets_cache/` to `/home/de1zyw/dota_overlay/.gitignore`.

- [ ] **Step 3: Manual verification**

Run:
```bash
cd /home/de1zyw/dota_overlay
python3 -c "
from assets import get_hero_icon_path, get_rank_icon_path
print(get_hero_icon_path(1))
print(get_rank_icon_path(85))
print(get_rank_icon_path(None))
"
```
Expected: first two lines print real file paths under `.assets_cache/` (e.g. `.../assets_cache/hero_icon_1.png`, `.../assets_cache/rank_icon_8.png`), and both files actually exist on disk with non-zero size (check with `ls -la .assets_cache/`). Third line prints `None` (no crash on missing rank_tier).

- [ ] **Step 4: Commit**

```bash
cd /home/de1zyw/dota_overlay
git add assets.py .gitignore
git commit -m "Add hero/rank icon fetch-and-cache module"
```

---

### Task 12: Visual redesign — icons + dark gradient theme

**Files:**
- Modify: `overlay_window.py` (full rewrite of the rendering internals; `render_lobby`/`show_overlay`/`hide_overlay`/`toggle_expanded` method names and signatures must NOT change — `app.py` calls them as-is)

**Interfaces:**
- Consumes: `assets.get_hero_icon_path`, `assets.get_rank_icon_path` (Task 11); `opendota_client.PlayerStats` fields (unchanged); `draft_matcher`'s `dict[int, int|None]` current-picks map (unchanged).
- Produces: same public interface as before (`OverlayWindow.render_lobby(radiant, dire, current_picks)`, `.show_overlay()`, `.hide_overlay()`, `.toggle_expanded()`) — Task 9's `app.py` and Task 8's hotkey wiring must keep working unmodified.

- [ ] **Step 1: Rewrite `overlay_window.py`**

```python
"""Frameless, always-on-top, translucent overlay window with a dark,
softly gradient-accented theme (pink/blue/purple glows on near-black,
inspired by a user-supplied reference palette, darkened/desaturated for
readability over live gameplay) and real hero/rank icons."""
from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui import QColor, QLinearGradient, QPainter, QPixmap
from PyQt6.QtWidgets import QApplication, QHBoxLayout, QLabel, QVBoxLayout, QWidget

import config
from assets import get_hero_icon_path, get_rank_icon_path

ACCENT_PINK = QColor("#FF9CE3")
ACCENT_BLUE = QColor("#7DD3FC")
ACCENT_PURPLE = QColor("#B388FF")
BASE_BG = QColor(10, 10, 16, 235)  # near-black, mostly opaque so text stays readable

ICON_SIZE = 24
HERO_ICON_SIZE = 20


def _winrate_color(winrate):
    if winrate is None:
        return config.COLOR_NEUTRAL
    if winrate >= config.WINRATE_GREEN:
        return config.COLOR_GREEN
    if winrate <= config.WINRATE_RED:
        return config.COLOR_RED
    return config.COLOR_NEUTRAL


def _icon_label(path, size):
    label = QLabel()
    if path:
        pixmap = QPixmap(path)
        if not pixmap.isNull():
            label.setPixmap(
                pixmap.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio,
                               Qt.TransformationMode.SmoothTransformation)
            )
    label.setFixedSize(size, size)
    return label


class _GradientPanel(QWidget):
    """Paints the dark base + three soft, low-opacity accent glows behind
    the content - a subtler, translucency-friendly take on the reference
    palette rather than the reference's full-opacity marketing-card look."""

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect())

        painter.setBrush(BASE_BG)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(rect, 14, 14)

        gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
        glow_pink = QColor(ACCENT_PINK)
        glow_pink.setAlpha(35)
        glow_blue = QColor(ACCENT_BLUE)
        glow_blue.setAlpha(35)
        glow_purple = QColor(ACCENT_PURPLE)
        glow_purple.setAlpha(35)
        gradient.setColorAt(0.0, glow_pink)
        gradient.setColorAt(0.5, glow_purple)
        gradient.setColorAt(1.0, glow_blue)
        painter.setBrush(gradient)
        painter.drawRoundedRect(rect, 14, 14)

        super().paintEvent(event)


def _player_row(stats, hero_id, expanded):
    row = QWidget()
    layout = QHBoxLayout(row)
    layout.setContentsMargins(4, 2, 4, 2)
    layout.setSpacing(6)

    if stats.hidden:
        label = QLabel(f"{stats.nickname} — профиль скрыт")
        label.setStyleSheet("color: #888899;")
        layout.addWidget(label)
        return row

    layout.addWidget(_icon_label(get_rank_icon_path(stats.rank_tier), ICON_SIZE))

    if hero_id:
        layout.addWidget(_icon_label(get_hero_icon_path(hero_id), HERO_ICON_SIZE))

    winrate_str = f"{stats.winrate:.0f}%" if stats.winrate is not None else "н/д"
    text = f"{stats.nickname} | WR {winrate_str} | {stats.last10}"
    if expanded:
        top_heroes_icons = "".join("🔸" for _ in stats.top_heroes[:3])
        text += f" | игр: {stats.total_games} | {top_heroes_icons} | {stats.dotabuff_url}"

    text_label = QLabel(text)
    text_label.setStyleSheet(f"color: {_winrate_color(stats.winrate)}; font-family: sans-serif;")
    layout.addWidget(text_label)
    layout.addStretch()
    return row


class OverlayWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowOpacity(config.WINDOW_OPACITY)

        self._expanded = False
        self._panel = _GradientPanel()
        self._layout = QVBoxLayout(self._panel)
        self._layout.setContentsMargins(12, 10, 12, 10)
        self._layout.setSpacing(4)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self._panel)

        self.move(config.WINDOW_MARGIN_PX, config.WINDOW_MARGIN_PX)

    def _clear_layout(self):
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

    def _section_header(self, text):
        label = QLabel(text)
        label.setStyleSheet(
            "color: white; font-weight: bold; font-family: sans-serif; "
            "letter-spacing: 1px; padding-top: 4px;"
        )
        return label

    def render_lobby(self, radiant, dire, current_picks):
        self._clear_layout()

        self._layout.addWidget(self._section_header("RADIANT"))
        for stats in radiant:
            self._layout.addWidget(_player_row(stats, current_picks.get(stats.account_id), self._expanded))

        self._layout.addWidget(self._section_header("DIRE"))
        for stats in dire:
            self._layout.addWidget(_player_row(stats, current_picks.get(stats.account_id), self._expanded))

        self._panel.adjustSize()
        self.adjustSize()

    def show_overlay(self):
        self.show()

    def hide_overlay(self):
        self.hide()

    def toggle_expanded(self):
        self._expanded = not self._expanded


if __name__ == "__main__":
    import sys

    from opendota_client import fetch_player_stats

    app = QApplication(sys.argv)
    window = OverlayWindow()

    radiant = [fetch_player_stats(111620041)]
    dire = []
    window.render_lobby(radiant, dire, {111620041: 1})
    window.show_overlay()

    sys.exit(app.exec())
```

- [ ] **Step 2: Manual verification**

Run: `cd /home/de1zyw/dota_overlay && QT_QPA_PLATFORM=xcb python3 overlay_window.py`
Expected: a rounded, dark, translucent window appears with a subtle pink→purple→blue diagonal glow behind the content, showing a RADIANT row with a rank icon, a hero icon (hardcoded hero_id=1/Anti-Mage in the demo), and colored winrate text for account 111620041, plus an empty DIRE section. Take a screenshot if possible (`magick import -window <id> /tmp/demo.png` after finding the window id via `wmctrl -l`, same approach used earlier in this project) and confirm the icons and gradient are visible, not just placeholder boxes.

- [ ] **Step 3: Commit**

```bash
cd /home/de1zyw/dota_overlay
git add overlay_window.py
git commit -m "Redesign overlay with hero/rank icons and dark gradient theme"
```

---

### Task 13: Radiant/Dire section headers — real faction icons

Added after user feedback on the live redesign: separate the "RADIANT"/"DIRE" section headers visually (not just as plain bold text) and add each faction's real icon (Radiant's ancient/throne emblem, Dire's emblem) next to the header text.

**No confirmed working icon URL exists yet for this** — several plausible CDN paths were tried live and all 404'd (`cdn.cloudflare.steamstatic.com/apps/dota2/images/dota_react/icons/{radiant,dire}.png`, `.../badges/{radiant,dire}.png`, `opendota.com/assets/images/dota2/{radiant,dire}.png` — the last one returns HTTP 200 but is actually OpenDota's SPA HTML fallback page, not a real image, a false positive worth remembering). This task starts with research, same as Task 11 did for hero/rank icons — do not guess a URL and ship it unverified.

**Files:**
- Modify: `assets.py` — add `get_faction_icon_path(team: str) -> str | None` (`team` is `"radiant"` or `"dire"`), following the exact same cache/never-raise pattern as `get_hero_icon_path`/`get_rank_icon_path`.
- Modify: `overlay_window.py` — `_section_header` (or equivalent) renders the icon (if found) beside the "RADIANT"/"DIRE" text, plus a bit more visual separation between the two team sections (e.g. a thin divider line or extra spacing) than currently exists.

- [ ] **Step 1: Research a real, working icon URL**

Try candidates with `curl -s -o /dev/null -w "%{http_code}\n" <url>` and inspect the actual downloaded bytes with `file <path>` before trusting a 200 status — OpenDota's own domain returns 200 with an HTML SPA shell for almost any path, which is a false positive (confirmed live during planning: `opendota.com/assets/images/dota2/radiant.png` → 200 but `file` shows "HTML document", not a PNG). A response only counts as real if `file` reports an actual image format (PNG/JPEG/etc.), not text/HTML.

Good places to check, in rough order of promise:
- Steam's CDN under other `dota_react` subpaths not yet tried (`.../dota_react/...` has proven reliable for heroes) — explore what subdirectories actually exist rather than guessing blind; e.g. try fetching a known-good hero icon's containing directory listing behavior, or check what asset paths the actual OpenDota/Dotabuff website loads for team logos by inspecting page source of a public match page (view-source or fetch the HTML and grep for `.png` URLs containing "radiant"/"dire"/"ancient").
- Dotabuff's static asset CDN (check their site's own served images for team icons the same way).
- The public GitHub repo `SteamDatabase/GameTracking-Dota2` (already referenced elsewhere in this project for `server_log.txt` context) mirrors Dota's actual game files — search it for panorama UI images related to Radiant/Dire ancients; note these may be in a compiled format (`.vtex_c`) requiring conversion, in which case this path is a dead end, not worth pursuing further than a quick check.

**If no real working PNG URL is found after a reasonable effort (don't burn more than ~15-20 minutes on this):** fall back to a locally-drawn placeholder — e.g. a small colored circle/triangle glyph drawn with Qt's `QPainter` (green-tinted for Radiant, red-tinted for Dire, matching the existing win/loss color convention already used elsewhere in this file) rather than a fetched image. Document in your report which path you took and why.

- [ ] **Step 2: Implement whichever path Step 1 lands on**

If a real URL was found, add `get_faction_icon_path` to `assets.py` mirroring the existing functions' structure (cache to `.assets_cache/`, never raise, return `None` on any failure). If falling back to a drawn glyph, implement it directly in `overlay_window.py` as a small helper, no `assets.py` involvement needed (nothing to fetch/cache).

Update the section header rendering in `overlay_window.py` to show the icon next to "RADIANT"/"DIRE", and add a bit of visual separation between the Radiant block and the Dire block (a thin horizontal rule, or extra vertical spacing — use your judgment for what looks clean given the existing dark gradient theme).

- [ ] **Step 3: Manual verification**

Run: `cd /home/de1zyw/dota_overlay && QT_QPA_PLATFORM=xcb python3 overlay_window.py` (or the fuller demo in `run_demo.py`), find the window via `wmctrl -l`, screenshot with `magick import -window <id> <path>.png`, and confirm both faction icons (or drawn glyphs) are visible next to their respective headers, with clear visual separation between the two sections.

- [ ] **Step 4: Commit**

```bash
cd /home/de1zyw/dota_overlay
git add assets.py overlay_window.py
git commit -m "Add Radiant/Dire faction icons to section headers"
```
