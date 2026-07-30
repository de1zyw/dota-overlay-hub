# Dota 2 Draft Stats Overlay — Design

## Purpose

An overlay that shows during the Dota 2 draft/pick phase, displaying stats for all 10 players in
the lobby (allies and enemies): rank, total matches, recent match form, most-played heroes,
meta ban stats, and (best-effort) each player's live hero pick as the draft happens.

Functionally equivalent to "Overplus" (see reference screenshot), but built entirely on **legal,
public data sources** — no packet interception, no memory reading. This distinction matters: a
wave of Dota account bans in 2024 is understood to have targeted tools reading game
memory/network traffic; this design deliberately avoids that mechanism category, using instead
the same kind of approach as the long-running, unbanned Stratz+.

## Data sources (all official/local, no reverse-engineering of network protocol)

1. **`server_log.txt`** — `<steam library>/steamapps/common/dota 2 beta/game/dota/server_log.txt`.
   Dota writes Match ID + all 10 players' Steam IDs to this file whenever a match is accepted
   (confirmed via ValveSoftware/Dota2-Gameplay#897 and a working reference parser,
   github.com/creepycheese/dota2-server-log, whose format is verified against a real multi-year
   log sample). Each match line repeats `<slot>:[U:1:<account_id>]` tokens; slot order
   `[0,1,2,3,4,128,129,130,131,132]` — first 5 = Radiant, last 5 = Dire. `account_id` is already
   the Steam32 id OpenDota expects, no conversion needed. Read the file from the end (it's
   append-only, can span years) to cheaply find the latest match without scanning it all.

2. **OpenDota public API** — reusing the approach already proven in `~/dota_stats_bot/opendota_api.py`
   and `steam_api.py` (throttling, retry/backoff, TTL cache already solved there): per-player
   profile/rank, win-loss, recent matches, top heroes by games. Also used for the aggregate
   "most banned heroes" meta stat — checked live: `/heroStats` only has `pro_ban` (professional
   matches), **no public-bracket ban field exists**. So "Best Bans" will show pro-scene ban
   rates, not "your MMR bracket this week" like the reference screenshot implied — that specific
   number isn't something OpenDota (or any legal public source) tracks for public matchmaking.

3. **Dota 2 Game State Integration (GSI)** — official mechanism (same system as CS:GO), configured
   via a `gamestate_integration_*.cfg` file. Its `Draft.Teams[team].PickIDs` field maps a
   **slot number within a team** to the hero picked in that slot, in real time during the draft.
   This is the only piece that can plausibly give "who is picking what, right now."

## The "Current pick" mechanism — best-effort, needs live verification

Hypothesis: GSI's per-team slot numbering (0-4) lines up with `server_log.txt`'s per-team slot
numbering (also 0-4 within Radiant/Dire, derived from `player_slot`). If so, joining
`(team, slot) → steam_id` (from server_log.txt) with `(team, slot) → hero_id` (from GSI draft)
gives `steam_id → hero_id`, entirely from two official, local, documented sources.

This alignment is **not confirmed** — GSI's public docs don't spell out the exact slot format.
Treat this as a best-effort feature: if the join produces inconsistent/missing data on a real
match, the "Current" column simply stays blank for that row rather than blocking the rest of
the overlay. **The user will provide a real `server_log.txt` sample and a captured GSI `draft`
payload from an actual match** — that's the point at which this gets calibrated for real, not
guessed further.

## Known limitation (not a bug): private profiles

If a player has "Expose Public Match Data" off in Dota's settings, OpenDota has no data for
them — same limitation every legal tool (including Stratz+) has. The UI shows "профиль скрыт"
for that row instead of stats; no workaround exists or is attempted.

## Architecture

- `opendota_client.py` — adapted from `dota_stats_bot/opendota_api.py` + `steam_api.py`. Given a
  `steam_id`, returns a `PlayerStats` dataclass: nickname, rank, total games, overall winrate,
  last-10 W-L string, top heroes (most played), dotabuff link. Handles hidden/private profiles by
  returning a "no data" marker instead of raising.
- `meta_client.py` — aggregate "most banned heroes" from OpenDota's `/heroStats` endpoint, sorted
  by `pro_ban` (confirmed live: field exists, no public-bracket equivalent exists).
- `lobby_watcher.py` — watches `server_log.txt` for growth, re-parses the newest
  `DOTA_GAMEMODE` match line on change, extracts `[(team, slot, steam_id), ...]` via the verified
  regex/slot-order scheme above. Exposes the latest lobby as `list[(team, steam_id)]`.
- `gsi_server.py` — minimal local HTTP server (stdlib `http.server` is enough, no new dependency)
  that Dota POSTs GSI JSON to. Extracts `Draft.Teams[team].PickIDs` per update.
- `draft_matcher.py` — joins `lobby_watcher` output with `gsi_server` draft state by
  `(team, slot)` to produce `steam_id → hero_id`. Isolated on its own so the "best-effort"
  join logic can be reworked without touching anything else once real data arrives.
- `overlay_window.py` — PyQt/PySide, frameless + always-on-top + translucent. Teams stacked
  top-to-bottom, one row per player: nick, rank, colored overall winrate, last-10 W-L,
  most-played heroes, current pick (if resolved), clickable dotabuff link. Extra stats collapse
  behind a hotkey. Meta "Best Bans" rendered as its own side panel, independent of player rows.
- `hotkeys.py` — global show/hide and expand/collapse via `pynput` (not `keyboard`, which needs
  root on Linux via evdev). Assumes X11 for now; Wayland global-hotkey/always-on-top reliability
  is a known open risk, not solved in this pass.
- `app.py` — wires it together: `lobby_watcher` fires on new match → fetch all 10 players' stats
  concurrently (thread pool, so the UI never blocks on network I/O) → render → auto-hide timer.
- `config.py` — corner position, auto-hide delay, hotkey bindings, winrate color thresholds.

## Error handling

- OpenDota network error / rate limit → row shows "н/д", never crashes the overlay.
- Hidden/private profile → nick only, "профиль скрыт", still show the dotabuff link if we have
  the id.
- `server_log.txt` not found / GSI server never receives a POST → overlay stays hidden with a
  small status indicator, rather than failing silently or crashing.
- Draft-matcher join producing no match for a slot → "Current" blank for that row only.

## Testing

No automated test suite (explicit user decision — this is a solo hands-on build, not a
TDD project). Verification is manual:
1. Run `app.py` against a **hardcoded list of real Steam IDs** (e.g. entries already in
   `dota_stats_bot/friends.db`) to confirm rendering, colors, collapsing, hotkeys, auto-hide —
   all without needing a live match.
2. Once the user sends a real `server_log.txt` sample: verify `lobby_watcher`'s parsing against
   it offline (no live game needed for this part).
3. Once the user sends a real GSI `draft` payload capture from an actual match: verify/fix the
   slot-join hypothesis in `draft_matcher.py`.
4. Full end-to-end confirmation happens whenever the user next plays a real match.

## Scope explicitly excluded from this project

Two other overlay ideas were raised (a personal/self-stats HUD, and a "look up whoever's
profile I just opened in-game" on-demand lookup) — both are separate sub-projects with their own
unresolved mechanisms, deliberately out of scope here to keep this spec buildable. They get their
own brainstorm/spec later.

## Platform

Linux (Arch/CachyOS, where Dota is actually installed and tested) is the primary target for this
pass. Windows portability (different Steam library path, different GSI cfg path, hotkey backend
behavior) is a known future concern, not solved now — the module boundaries above are chosen so
that porting later touches `config.py` and `hotkeys.py` rather than everything.
