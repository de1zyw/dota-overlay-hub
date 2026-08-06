# Richer Player Stats Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enrich the self-stats/profile-lookup/last-match windows with KDA+GPM/XPM per match, hero winrates, a leaderboard-rank badge, frequent teammates, and (self-account only) locally-cached per-hero personal bests/streaks that don't exist anywhere in the public OpenDota API.

**Architecture:** Extend `opendota_client.py`'s data shapes (already-fetched API responses just keep more fields) and add two small new modules (`assets.get_avatar_path` for peer avatars, `local_hero_stats.py` for the local `stats.dat` file) - all rendering changes land in `player_stats_window.py`, which is the one window shared by self-stats/profile-lookup/last-match-recap. The compact draft row (`overlay_window.py`) is explicitly NOT touched beyond one optional parameter default - it stays icon-only per the approved spec.

**Tech Stack:** Python, PyQt6, `requests` (existing), new dependency: `vdf` (PyPI) for Task 7's binary-KeyValues parsing.

## Global Constraints

- No automated test suite in this project (standing project convention - see any existing file in `docs/superpowers/specs/`). Every task's verification step is: `python3 -m py_compile` on touched files, plus a real-data check (either a throwaway script hitting the live OpenDota API, or manual visual confirmation via the running app) - never invent a pytest suite.
- Never guess field names from memory - every OpenDota field used in this plan was verified against a real API response during the design phase (see spec's per-section notes); if a task needs a field not already verified in the spec, verify it live before writing the task's code (this only applies to Task 5/7's `stats.dat` parsing, which is explicitly unverified going in).
- Match this project's existing code style: dataclasses (not namedtuples) for structured data, inline PyQt stylesheets matching the dark-gradient theme already used throughout `overlay_window.py`/`player_stats_window.py` (colors: `color: white`/`#aaaaaa`/`#888899` for text hierarchy, `font-family: sans-serif`, existing `config.COLOR_GREEN`/`COLOR_RED`/`COLOR_NEUTRAL` for winrate-colored text via `_winrate_color()`).
- Every new/changed function that can fail (network, missing file, bad parse) must degrade to `None`/empty and never raise into the caller - same convention as every existing function in `opendota_client.py`/`assets.py`/`last_match_watcher.py`.
- Commit after each task, following this repo's existing commit-message style (see `git log` - explain the *why*, not just the *what*).

---

### Task 1: `RecentMatch` dataclass carrying KDA/GPM/XPM

**Files:**
- Modify: `opendota_client.py:201-292` (`PlayerStats.recent_matches` field + `fetch_player_stats`'s `recent_matches` construction)
- Modify: `overlay_window.py:105-133` (`_match_history_group`'s unpacking)
- Modify: `app.py:219` (`profile_lookup_history.append`'s `match_ids` extraction)

**Interfaces:**
- Produces: `opendota_client.RecentMatch` - a `@dataclass` with fields `hero_id: int`, `won: bool`, `match_id: int`, `kills: int`, `deaths: int`, `assists: int`, `gpm: int`, `xpm: int`. `PlayerStats.recent_matches` is now `list[RecentMatch]` instead of `list[tuple]`.

- [ ] **Step 1: Add the `RecentMatch` dataclass to `opendota_client.py`**

Add directly above the existing `PlayerStats` dataclass (around line 201):

```python
@dataclass
class RecentMatch:
    hero_id: int
    won: bool
    match_id: int
    kills: int
    deaths: int
    assists: int
    gpm: int
    xpm: int
```

- [ ] **Step 2: Build `RecentMatch` objects instead of bare tuples in `fetch_player_stats`**

In `opendota_client.py`, replace the existing `recent_matches` comprehension (around line 270-273):

```python
    recent_matches = [
        (m.get("hero_id"), m.get("radiant_win") == (m.get("player_slot", 0) < 128), m.get("match_id"))
        for m in recent[:10]
    ]
```

with:

```python
    recent_matches = [
        RecentMatch(
            hero_id=m.get("hero_id"),
            won=m.get("radiant_win") == (m.get("player_slot", 0) < 128),
            match_id=m.get("match_id"),
            kills=m.get("kills") or 0,
            deaths=m.get("deaths") or 0,
            assists=m.get("assists") or 0,
            gpm=m.get("gold_per_min") or 0,
            xpm=m.get("xp_per_min") or 0,
        )
        for m in recent[:10]
    ]
```

Update the field's type comment on `PlayerStats.recent_matches` (currently `# [(hero_id, won: bool, match_id: int), ...], newest first, max 10`) to `# list[RecentMatch], newest first, max 10`.

- [ ] **Step 3: Update `_match_history_group`'s unpacking in `overlay_window.py`**

Change (line 114):
```python
    for hero_id, won, _match_id in recent_matches[:MATCH_HISTORY_COUNT]:
```
to:
```python
    for match in recent_matches[:MATCH_HISTORY_COUNT]:
        hero_id, won = match.hero_id, match.won
```
(Keep the rest of the loop body as-is - it only used `hero_id`/`won`, never `_match_id`.)

- [ ] **Step 4: Update `app.py`'s `match_ids` extraction**

Change (line 219):
```python
        match_ids = [match_id for _, _, match_id in stats.recent_matches if match_id is not None]
```
to:
```python
        match_ids = [m.match_id for m in stats.recent_matches if m.match_id is not None]
```

- [ ] **Step 5: Verify**

```bash
cd /home/de1zyw/dota_overlay && python3 -m py_compile opendota_client.py overlay_window.py app.py
python3 -c "
import opendota_client as od
stats = od.fetch_player_stats(111620041)  # Miracle-, confirmed public data
m = stats.recent_matches[0]
print(m)
assert isinstance(m, od.RecentMatch)
assert m.kills >= 0 and m.gpm > 0
print('OK')
"
```
Expected: prints a real `RecentMatch(...)` with nonzero `kills`/`gpm`, then `OK`.

- [ ] **Step 6: Commit**

```bash
git add opendota_client.py overlay_window.py app.py
git commit -m "$(cat <<'EOF'
Carry KDA/GPM/XPM through recent_matches instead of discarding them

OpenDota's recentMatches endpoint already returns this data - it was
being fetched and thrown away every time. First step toward showing it
in player_stats_window (richer-player-stats spec, task 1/8).
EOF
)"
```

---

### Task 2: Show KDA under each recent-match icon in `player_stats_window.py`

**Files:**
- Modify: `overlay_window.py:105-133` (`_match_history_group` gains an opt-in parameter)
- Modify: `player_stats_window.py:127-128` (the two calls that should opt in)

**Interfaces:**
- Consumes: `RecentMatch` from Task 1.
- Produces: `_match_history_group(recent_matches, show_kda=False)` - unchanged default behavior for the one existing caller that doesn't pass `show_kda` (the compact draft row, `overlay_window.py:266`, stays icon-only).

- [ ] **Step 1: Add the `show_kda` parameter to `_match_history_group`**

Replace the whole function body in `overlay_window.py` (lines 105-133):

```python
def _match_history_group(recent_matches, show_kda=False):
    """Small hero-icon strip for the last few matches, newest first, each
    ringed green (win) or red (loss) - a win is always green, never the
    background's purple accent, so the win/loss signal stays unambiguous.
    show_kda=True (player_stats_window.py only - the compact draft row has
    no room for it) adds a small "K/D/A" caption under each icon."""
    group = QWidget()
    layout = QHBoxLayout(group)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(ICON_GAP)

    for match in recent_matches[:MATCH_HISTORY_COUNT]:
        border_color = config.COLOR_GREEN if match.won else config.COLOR_RED
        inner = MATCH_ICON_SIZE - 2 * MATCH_ICON_BORDER
        label = QLabel()
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        path = get_hero_icon_path(match.hero_id)
        if path:
            pixmap = QPixmap(path)
            if not pixmap.isNull():
                label.setPixmap(
                    pixmap.scaled(inner, inner, Qt.AspectRatioMode.KeepAspectRatio,
                                   Qt.TransformationMode.FastTransformation)
                )
        label.setFixedSize(MATCH_ICON_SIZE, MATCH_ICON_SIZE)
        label.setStyleSheet(
            f"border: {MATCH_ICON_BORDER}px solid {border_color}; border-radius: 4px;"
        )

        if not show_kda:
            layout.addWidget(label)
            continue

        # Icon + caption stacked - a plain QLabel can't hold both, and the
        # caption is wider than the 18px icon, so this is a small column,
        # not just the bare icon. Qt sizes each column to its widest child
        # (the caption text) automatically - no manual width math needed.
        entry = QWidget()
        entry_layout = QVBoxLayout(entry)
        entry_layout.setContentsMargins(0, 0, 0, 0)
        entry_layout.setSpacing(2)
        entry_layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        entry_layout.addWidget(label, 0, Qt.AlignmentFlag.AlignHCenter)
        kda = QLabel(f"{match.kills}/{match.deaths}/{match.assists}")
        kda.setStyleSheet("color: #aaaaaa; font-family: sans-serif; font-size: 9px;")
        kda.setAlignment(Qt.AlignmentFlag.AlignCenter)
        entry_layout.addWidget(kda)
        layout.addWidget(entry)

    return group
```

This needs `QVBoxLayout` imported in `overlay_window.py` - check the existing `from PyQt6.QtWidgets import (...)` block near the top of the file and add `QVBoxLayout` to it if not already present.

- [ ] **Step 2: Opt in from `player_stats_window.py`**

Change (lines 127-128):
```python
        self._layout.addWidget(_match_history_group(stats.recent_matches[0:5]))
        self._layout.addWidget(_match_history_group(stats.recent_matches[5:10]))
```
to:
```python
        self._layout.addWidget(_match_history_group(stats.recent_matches[0:5], show_kda=True))
        self._layout.addWidget(_match_history_group(stats.recent_matches[5:10], show_kda=True))
```

- [ ] **Step 3: Verify**

```bash
cd /home/de1zyw/dota_overlay && python3 -m py_compile overlay_window.py player_stats_window.py
```
Then manually: run the app (or reuse a throwaway script like this session's earlier `integration_check.py` pattern - construct `PlayerStatsWindow`, call `render_stats(fetch_player_stats(111620041))`, `show_overlay()`, confirm visually that each of the 10 match icons has a `K/D/A` caption underneath, and that the compact draft row (via `OverlayWindow.render_lobby`) is unchanged (icons only, no captions).

- [ ] **Step 4: Commit**

```bash
git add overlay_window.py player_stats_window.py
git commit -m "$(cat <<'EOF'
Show KDA caption under each recent-match icon in player_stats_window

Opt-in via a new show_kda param on _match_history_group so the compact
draft row (no room for captions) is unaffected - only self-stats/
profile-lookup/last-match-recap opt in (richer-player-stats spec, task 2/8).
EOF
)"
```

---

### Task 3: Top heroes with winrate

**Files:**
- Modify: `opendota_client.py:210,279` (`top_heroes` field shape)
- Modify: `player_stats_window.py` (new "Топ герои" section)

**Interfaces:**
- Produces: `PlayerStats.top_heroes` is now `list[tuple[hero_id: int, games: int, win: int]]` instead of `list[int]`.
- Consumes for rendering: `assets.get_hero_icon_path(hero_id)` (existing).

- [ ] **Step 1: Change `top_heroes` to carry games/win**

In `opendota_client.py`, change the field comment (line 210) from
`top_heroes: list = field(default_factory=list)` (no change to the line itself, just the shape of what's stored) and change the construction (line 279):

```python
    top_heroes = [h["hero_id"] for h in heroes if h.get("games", 0) > 0][:3]
```
to:
```python
    top_heroes = [
        (h["hero_id"], h.get("games", 0), h.get("win", 0))
        for h in heroes if h.get("games", 0) > 0
    ][:3]
```

- [ ] **Step 2: Confirm the one existing consumer still works unchanged**

`overlay_window.py:271` (`"".join("\U0001F538" for _ in stats.top_heroes[:3])`) only counts elements via `_` - it doesn't unpack them, so this line needs NO change. Read it to confirm this is still true before moving on (it was true when this plan was written; if the surrounding code has changed, re-check).

- [ ] **Step 3: Add a "Топ герои" section to `player_stats_window.py`**

In `render_stats`, right after the existing `history_label`/`_match_history_group` block (after the line `self._layout.addWidget(_match_history_group(stats.recent_matches[5:10], show_kda=True))`), add:

```python
        if stats.top_heroes:
            top_heroes_label = QLabel("ТОП ГЕРОИ")
            top_heroes_label.setStyleSheet(
                "color: #888899; font-family: sans-serif; font-size: 11px; "
                "font-weight: bold; letter-spacing: 1px;"
            )
            self._layout.addWidget(top_heroes_label)

            top_heroes_row = QWidget()
            top_heroes_layout = QHBoxLayout(top_heroes_row)
            top_heroes_layout.setContentsMargins(0, 0, 0, 0)
            top_heroes_layout.setSpacing(12)
            for hero_id, games, win in stats.top_heroes:
                entry = QWidget()
                entry_layout = QVBoxLayout(entry)
                entry_layout.setContentsMargins(0, 0, 0, 0)
                entry_layout.setSpacing(2)
                entry_layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)
                entry_layout.addWidget(
                    _icon_label(get_hero_icon_path(hero_id), 32), 0, Qt.AlignmentFlag.AlignHCenter
                )
                hero_winrate = (win / games * 100) if games else None
                caption = QLabel(f"{hero_winrate:.0f}% · {games}" if hero_winrate is not None else "н/д")
                caption.setStyleSheet(
                    f"color: {_winrate_color(hero_winrate)}; font-family: sans-serif; font-size: 10px;"
                )
                caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
                entry_layout.addWidget(caption)
                top_heroes_layout.addWidget(entry)
            top_heroes_layout.addStretch()
            self._layout.addWidget(top_heroes_row)
```

This needs `get_hero_icon_path` imported in `player_stats_window.py` - the existing import line is `from assets import get_rank_icon_path`; change it to `from assets import get_hero_icon_path, get_rank_icon_path`.

- [ ] **Step 4: Verify**

```bash
cd /home/de1zyw/dota_overlay && python3 -m py_compile opendota_client.py player_stats_window.py
python3 -c "
import opendota_client as od
stats = od.fetch_player_stats(111620041)
print(stats.top_heroes)
assert all(len(t) == 3 for t in stats.top_heroes)
print('OK')
"
```
Then manually confirm visually (same throwaway-render approach as Task 2) - a "ТОП ГЕРОИ" row with up to 3 hero icons, each with a winrate% + game count underneath.

- [ ] **Step 5: Commit**

```bash
git add opendota_client.py player_stats_window.py
git commit -m "$(cat <<'EOF'
Show top-hero winrates in player_stats_window (was icon-only, no numbers)

top_heroes already fetched games/win from OpenDota and discarded them -
now kept and rendered as a winrate% + game count under each icon
(richer-player-stats spec, task 3/8).
EOF
)"
```

---

### Task 4: Leaderboard-rank badge (honest MMR cap)

**Files:**
- Modify: `opendota_client.py` (`PlayerStats` gains `leaderboard_rank`)
- Modify: `player_stats_window.py` (conditional badge next to the rank icon)

**Interfaces:**
- Produces: `PlayerStats.leaderboard_rank: int = None` - non-null ONLY for top-tier leaderboard players (verified live: `None` for a normal account). Callers must not assume this is ever populated for a typical user.

- [ ] **Step 1: Add the field and populate it**

In `opendota_client.py`, add to the `PlayerStats` dataclass (near `rank_tier`):
```python
    leaderboard_rank: int = None
```
In `fetch_player_stats`, in the `PlayerStats(...)` construction (around line 281-285), add:
```python
        leaderboard_rank=profile.get("leaderboard_rank"),
```
(`profile` here is the full `/players/{id}` response already fetched via `profile_f.result()` - `leaderboard_rank` is a real top-level field on it, verified live.)

- [ ] **Step 2: Render the badge conditionally**

In `player_stats_window.py`'s `render_stats`, the `header` block currently is:
```python
        header = QHBoxLayout()
        header.addWidget(_icon_label(get_rank_icon_path(stats.rank_tier), RANK_ICON_SIZE))
        nickname = QLabel(stats.nickname)
```
After the rank icon line, insert:
```python
        if stats.leaderboard_rank is not None:
            leaderboard_badge = QLabel(f"Топ #{stats.leaderboard_rank}")
            leaderboard_badge.setStyleSheet(
                f"color: {config.COLOR_GREEN}; font-family: sans-serif; "
                "font-size: 11px; font-weight: bold;"
            )
            header.addWidget(leaderboard_badge)
```

- [ ] **Step 3: Verify**

```bash
cd /home/de1zyw/dota_overlay && python3 -m py_compile opendota_client.py player_stats_window.py
python3 -c "
import opendota_client as od
stats = od.fetch_player_stats(111620041)
print('leaderboard_rank:', stats.leaderboard_rank)
"
```
Expected: prints `None` (Miracle- isn't necessarily on the leaderboard endpoint OpenDota tracks this way either) or a real integer - either is a valid pass, this just confirms the field round-trips without crashing. Visually confirm no badge appears for an account with `None` (the common case) and no layout glitch.

- [ ] **Step 4: Commit**

```bash
git add opendota_client.py player_stats_window.py
git commit -m "$(cat <<'EOF'
Add leaderboard-rank badge (only shows for top-tier accounts)

Exact MMR is confirmed unavailable publicly for regular accounts (Valve
hid it in 2019) - leaderboard_rank is the only additional real signal,
and it's None for everyone else, so the badge only renders when present
(richer-player-stats spec, task 4/8).
EOF
)"
```

---

### Task 5: Frequent teammates ("peers"), self-stats only

**Files:**
- Modify: `opendota_client.py` (new `fetch_peers` function)
- Modify: `assets.py` (new `get_avatar_path` - peer avatars are arbitrary URLs, unlike the fixed hero/rank icon sets, so can't be prefetched)
- Modify: `player_stats_window.py` (`render_stats` gains an `is_self` parameter; new peers section)
- Modify: `app.py` (the one call site that renders self-stats passes `is_self=True`)

**Interfaces:**
- Produces: `opendota_client.fetch_peers(account_id) -> list[dict] | None`. Each dict has `account_id`, `personaname`, `avatarfull`, `win`, `games` (subset of the real API response - verified live, other fields exist but aren't used). `None` on any OpenDota error (same convention as `search_players`).
- Produces: `assets.get_avatar_path(account_id, avatar_url) -> str | None` - local cache path or `None` on download failure.
- Produces: `player_stats_window.PlayerStatsWindow.render_stats(stats, empty_message=..., is_self=False)`.

- [ ] **Step 1: Add `fetch_peers` to `opendota_client.py`**

Add near `search_players`:
```python
def fetch_peers(account_id, limit=3):
    """Top `limit` most-frequent teammates by games played together, or
    None on any OpenDota-side error (same convention as search_players -
    None means "couldn't ask", not "nobody found"). Self-account use only
    (see player_stats_window.py) - this endpoint is about the QUERIED
    account's own peers, not meaningful on a looked-up stranger's profile."""
    try:
        peers = _cached_get(f"/players/{account_id}/peers", ttl=300) or []
    except OpenDotaError:
        return None
    peers = sorted(peers, key=lambda p: p.get("games", 0), reverse=True)[:limit]
    return [
        {
            "account_id": p.get("account_id"),
            "personaname": p.get("personaname") or f"[{p.get('account_id')}]",
            "avatarfull": p.get("avatarfull"),
            "win": p.get("win", 0),
            "games": p.get("games", 0),
        }
        for p in peers
    ]
```

- [ ] **Step 2: Add `get_avatar_path` to `assets.py`**

Add near `get_faction_icon_path`:
```python
def get_avatar_path(account_id, avatar_url):
    """Unlike hero/rank icons (a small fixed enumerable set, prefetched by
    prefetch_all_icons), peer avatars are one arbitrary URL per arbitrary
    account_id - unbounded, so this is fetched on demand, not prefetched."""
    if not avatar_url or not account_id:
        return None
    dest = os.path.join(CACHE_DIR, f"avatar_{account_id}.jpg")
    return _download(avatar_url, dest)
```

- [ ] **Step 3: Add `is_self` param and the peers section to `player_stats_window.py`**

Change the `render_stats` signature:
```python
    def render_stats(self, stats, empty_message="Steam-аккаунт не определён — стата недоступна", is_self=False):
```

At the end of `render_stats`, right before the final `self._panel.adjustSize()` / `self.adjustSize()` pair, insert:
```python
        if is_self:
            from opendota_client import fetch_peers
            from assets import get_avatar_path
            peers = fetch_peers(stats.account_id)
            if peers:
                peers_label = QLabel("ЧАСТО ИГРАЕШЬ С")
                peers_label.setStyleSheet(
                    "color: #888899; font-family: sans-serif; font-size: 11px; "
                    "font-weight: bold; letter-spacing: 1px;"
                )
                self._layout.addWidget(peers_label)
                for peer in peers:
                    row = QHBoxLayout()
                    row.addWidget(_icon_label(get_avatar_path(peer["account_id"], peer["avatarfull"]), 24))
                    name = QLabel(peer["personaname"])
                    name.setStyleSheet("color: white; font-family: sans-serif; font-size: 12px;")
                    row.addWidget(name)
                    row.addStretch()
                    together_wr = (peer["win"] / peer["games"] * 100) if peer["games"] else None
                    wr_label = QLabel(
                        f"{together_wr:.0f}% · {peer['games']} игр" if together_wr is not None else "н/д"
                    )
                    wr_label.setStyleSheet(
                        f"color: {_winrate_color(together_wr)}; font-family: sans-serif; font-size: 11px;"
                    )
                    row.addWidget(wr_label)
                    self._layout.addLayout(row)
```

(The two local imports match this file's existing pattern in the rest of the codebase for optional/rarely-needed imports - e.g. `region_calibrator.py`'s import style; if the project's convention is actually top-of-file imports throughout `player_stats_window.py` specifically, move `fetch_peers`/`get_avatar_path` to the top-level import block instead for consistency - check the file's existing import style before choosing.)

- [ ] **Step 4: Pass `is_self=True` from the self-stats call site**

In `app.py`, find `_on_self_stats_ready` (in `_MainThreadBridge`):
```python
    def _on_self_stats_ready(self, stats):
        ...
        if self._player_stats_window.isVisible():
            self._player_stats_window.hide_stats()
        else:
            self._player_stats_window.render_stats(stats)
            self._player_stats_window.show_stats()
```
Change `self._player_stats_window.render_stats(stats)` to `self._player_stats_window.render_stats(stats, is_self=True)`.

- [ ] **Step 5: Verify**

```bash
cd /home/de1zyw/dota_overlay && python3 -m py_compile opendota_client.py assets.py player_stats_window.py app.py
python3 -c "
import opendota_client as od
peers = od.fetch_peers(111620041)
print(peers)
assert peers is None or all('personaname' in p for p in peers)
print('OK')
"
```
Then manually confirm: self-stats hotkey shows a "ЧАСТО ИГРАЕШЬ С" section; profile-lookup (a stranger, `is_self=False` by default) does NOT show this section even though the underlying data would be fetchable - confirms the gating actually works, not just that the code doesn't crash.

- [ ] **Step 6: Commit**

```bash
git add opendota_client.py assets.py player_stats_window.py app.py
git commit -m "$(cat <<'EOF'
Add frequent-teammates section, self-stats only

New fetch_peers()/get_avatar_path() - gated behind a new is_self param
on render_stats so a looked-up stranger's profile never shows this (the
peers endpoint is about the queried account's own history, not
meaningful on someone else's profile) (richer-player-stats spec, task 5/8).
EOF
)"
```

---

### Task 6: Verify `vdf.binary_loads()` against the real `stats.dat` (throwaway script, no app changes)

**Files:**
- Create: `/tmp/verify_stats_dat.py` (explicitly NOT part of the project - a one-off verification script, matches this session's own established pattern of verifying against real data before writing real code)

**Interfaces:** None (this task produces no code the app uses - it's a go/no-go check before Task 7).

- [ ] **Step 1: Check `vdf` is installable**

```bash
pip install vdf --break-system-packages 2>&1 | tail -5
python3 -c "import vdf; print(vdf.__file__)"
```
If this fails, check the AUR for a `python-vdf` package instead (`yay -Ss python-vdf` on the real Arch machine, not this dev sandbox) before proceeding - do not guess a package name that hasn't actually been checked.

- [ ] **Step 2: Write and run the verification script**

This needs a REAL `stats.dat` file - it only exists on the user's real machine (`~/.local/share/Steam/userdata/<account_id>/570/remote/cfg/stats.dat`, confirmed present and inspected via hex dump earlier this session), not in this dev sandbox. Write:

```python
#!/usr/bin/env python3
import os
import vdf

path = os.path.expanduser(
    "~/.local/share/Steam/userdata/471425583/570/remote/cfg/stats.dat"
)
with open(path, "rb") as f:
    raw = f.read()

# First 8 bytes are VBKV's own header (4-byte "VBKV" magic + 4-byte
# checksum, confirmed via this session's hex-dump work on last_match.dat -
# stats.dat shares the same VBKV wrapper) - the actual binary-KeyValues
# payload vdf.binary_loads() expects starts right after that.
payload = raw[8:]
parsed = vdf.binary_loads(payload)
print(type(parsed))
print(list(parsed.keys())[:5])

standings = parsed.get("Stats", {}).get("hero_standings", {}).get("standings", {})
print("hero block count:", len(standings))
first_hero = next(iter(standings.values()))
print(first_hero)
```

Run it on the real machine (via SSH into the Arch VM if it's up, matching how `last_match_watcher.py`'s own path was validated earlier this session, or directly if working on bare-metal by then).

- [ ] **Step 3: Record the outcome**

Two possible outcomes - both are valid task completions, this is a go/no-go check:
- **It parses cleanly** and `first_hero` contains fields matching the spec's list (`hero_id`, `wins`, `losses`, `win_streak`, etc.) → proceed to Task 7 using this exact approach.
- **It doesn't parse** (wrong header offset, `vdf`'s binary format doesn't match this specific VBKV variant, etc.) → do NOT proceed to Task 7 as planned. Instead, go back to the raw hex dump (already captured this session) and hand-write a minimal parser for exactly the fields `stats.dat` needs, the same "narrow, proven-against-real-data" style as `last_match_watcher.read_last_match_id` - re-scope Task 7 accordingly before writing it.

No commit for this task - it's a throwaway script in `/tmp`, not part of the repo.

---

### Task 7: `local_hero_stats.py` - real module, wired to `requirements.txt`

**Files:**
- Create: `local_hero_stats.py`
- Modify: `requirements.txt`

**Interfaces:**
- Produces: `local_hero_stats.get_hero_standings(account_id) -> dict[hero_id: int, dict] | None`. Each inner dict has (at minimum) `win_streak`, `best_win_streak`, `best_kills`, `best_gpm`, `best_xpm` - exact key set depends on Task 6's confirmed real structure. Returns `None` if the file doesn't exist, can't be read, or fails to parse - never raises (same convention as `last_match_watcher.read_last_match_id`).

- [ ] **Step 1: Add `vdf` to `requirements.txt`**

Append `vdf==...` (exact version pinned to whatever Task 6 confirmed installs cleanly - check `pip show vdf` for the installed version) as a new line.

- [ ] **Step 2: Write `local_hero_stats.py`**

Base this directly on Task 6's confirmed-working script - do not re-derive the header-skip offset or key names from scratch, reuse exactly what Task 6 verified. Shape (fill in the real key names Task 6 confirmed - this is a skeleton, not literal final code, since Task 6's actual output isn't known yet when this plan was written):

```python
"""Reads per-hero personal-best/streak stats out of Dota's local Steam
Cloud cache file - data that doesn't exist anywhere in public OpenDota
(confirmed: OpenDota's own /players/{id}/heroes has no streak/peak
fields). Same file family as last_match_watcher.py's last_match.dat
(VBKV/binary-KeyValues), but with a repeating per-hero block structure
that needed a real parser (see Task 6's verification script) instead of
last_match.dat's single-field byte-offset hack."""
import os

import vdf

from steam_library import _find_steam_root

# Confirmed via this session's hex-dump work: VBKV's own header is 4 bytes
# of "VBKV" magic + 4 bytes of checksum, before the actual binary-
# KeyValues payload vdf.binary_loads() parses.
_VBKV_HEADER_SIZE = 8


def _stats_dat_path(account_id):
    if account_id is None:
        return None
    root = _find_steam_root()
    if root is None:
        return None
    return os.path.join(root, "userdata", str(account_id), "570", "remote", "cfg", "stats.dat")


def get_hero_standings(account_id):
    path = _stats_dat_path(account_id)
    if path is None:
        return None
    try:
        with open(path, "rb") as f:
            raw = f.read()
    except OSError:
        return None
    try:
        parsed = vdf.binary_loads(raw[_VBKV_HEADER_SIZE:])
        standings = parsed["Stats"]["hero_standings"]["standings"]
    except (KeyError, TypeError, ValueError) as e:
        return None
    result = {}
    for entry in standings.values():
        hero_id = entry.get("hero_id")
        if hero_id is not None:
            result[int(hero_id)] = entry
    return result
```

- [ ] **Step 3: Verify**

```bash
cd /home/de1zyw/dota_overlay && python3 -m py_compile local_hero_stats.py
```
Then on the real machine (same access path as Task 6):
```bash
python3 -c "
import local_hero_stats as lhs
standings = lhs.get_hero_standings(471425583)
print(len(standings) if standings else standings)
print(next(iter(standings.items())) if standings else None)
"
```
Expected: a real dict keyed by hero_id, non-empty (the account has played matches this session confirmed).

- [ ] **Step 4: Commit**

```bash
git add local_hero_stats.py requirements.txt
git commit -m "$(cat <<'EOF'
Add local_hero_stats.py - reads per-hero streaks/bests from Steam's local cache

Confirmed via Task 6's verification script that vdf.binary_loads() parses
the real stats.dat correctly. This data (win_streak, best_kills/gpm/xpm,
etc. per hero) doesn't exist anywhere in public OpenDota - local-only,
instant, no network round trip (richer-player-stats spec, task 7/8).
EOF
)"
```

---

### Task 8: Render local bests/streaks in `player_stats_window.py`, self-stats only

**Files:**
- Modify: `player_stats_window.py`

**Interfaces:**
- Consumes: `local_hero_stats.get_hero_standings(account_id)` from Task 7, `PlayerStats.top_heroes` from Task 3 (renders one block per top hero that also has local data).

- [ ] **Step 1: Add the local-bests block, inside the existing `if is_self:` branch from Task 5**

Add this right after the peers section built in Task 5 (still inside `if is_self:`):
```python
            from local_hero_stats import get_hero_standings
            standings = get_hero_standings(stats.account_id)
            if standings and stats.top_heroes:
                bests_label = QLabel("ЛИЧНЫЕ РЕКОРДЫ")
                bests_label.setStyleSheet(
                    "color: #888899; font-family: sans-serif; font-size: 11px; "
                    "font-weight: bold; letter-spacing: 1px;"
                )
                self._layout.addWidget(bests_label)
                for hero_id, _games, _win in stats.top_heroes:
                    entry = standings.get(hero_id)
                    if not entry:
                        continue
                    row = QHBoxLayout()
                    row.addWidget(_icon_label(get_hero_icon_path(hero_id), 24))
                    streak = entry.get("win_streak", 0)
                    streak_text = f"  •  винстрик {streak}" if streak else ""
                    text = QLabel(
                        f"рекорд: {entry.get('best_kills', 0)}/{entry.get('best_gpm', 0)} gpm{streak_text}"
                    )
                    text.setStyleSheet("color: #cccccc; font-family: sans-serif; font-size: 11px;")
                    row.addWidget(text)
                    row.addStretch()
                    self._layout.addLayout(row)
```

Exact key names (`win_streak`, `best_kills`, `best_gpm`) must match whatever Task 6/7 actually confirmed - if the real parsed keys differ from this plan's assumption (written before Task 6 ran), use the real ones instead of what's written here.

- [ ] **Step 2: Verify**

```bash
cd /home/de1zyw/dota_overlay && python3 -m py_compile player_stats_window.py
```
Manually: self-stats hotkey shows a "ЛИЧНЫЕ РЕКОРДЫ" block under the peers section, one row per top hero that has local data, with real numbers (not zeros/placeholders) for at least one hero with actual games played. Confirm profile-lookup (a stranger) never shows this block.

- [ ] **Step 3: Commit**

```bash
git add player_stats_window.py
git commit -m "$(cat <<'EOF'
Render local per-hero bests/streaks in self-stats (richer-player-stats spec, task 8/8)

Completes the richer-player-stats spec - self-stats now shows data that
exists nowhere in public OpenDota, sourced entirely from the local Steam
Cloud cache with zero network cost.
EOF
)"
```
