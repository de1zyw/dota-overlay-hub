# Richer player stats — design

## Purpose

Reframe: the project's flagship was originally "Драфт-статы" (live roster
during draft), which is confirmed unreachable — modern Dota's Source 2
client doesn't write roster data to any local file, GSI only exposes the
local player's own identity during a live game, and the GC protocol path
(ValvePython/dota2, a Steam bot account) is explicitly disabled server-side
by Valve for arbitrary player lookups (see `error_codes.py`'s network-layer
codes and this session's research). What already works reliably — self-
stats, OCR profile-lookup, and the new last-match recap — becomes the real
product: never leave Dota to check Dotabuff. This spec makes those three
features richer instead of chasing the unreachable live-roster goal.

All fields below are verified against real OpenDota API responses (not
assumed from memory) - see field lists per section.

## 1. KDA + GPM/XPM per recent match

`opendota_client.fetch_player_stats`'s `recent_matches` currently keeps
only `(hero_id, won, match_id)` per match, discarding everything else
`/players/{id}/recentMatches` returns. Confirmed real fields available on
that same response: `kills`, `deaths`, `assists`, `gold_per_min`,
`xp_per_min`, plus `hero_damage`, `last_hits`, `party_size`.

- `PlayerStats.recent_matches` entries become a small dataclass/namedtuple
  (`RecentMatch`) instead of a bare tuple: `hero_id`, `won`, `match_id`,
  `kills`, `deaths`, `assists`, `gpm`, `xpm`. Existing tuple-unpacking call
  sites (`overlay_window._match_history_group`, `app.py`'s
  `profile_lookup_history.append`) need updating to the new field names.
- **Compact draft row**: unchanged visually — no room for KDA text at that
  size, this was explicitly not requested there.
- **`player_stats_window.py`** (self-stats / profile-lookup / last-match
  recap — the window with room): each of the 10 recent-match icons gains a
  small KDA line on hover-equivalent always-visible text underneath (e.g.
  `16/12/21`), matching the existing dark-theme small-caption style already
  used for winrate under hero icons elsewhere in this window.

## 2. Top heroes with winrate

`/players/{id}/heroes` already returns `games`/`win` per hero_id;
`opendota_client.fetch_player_stats` currently keeps only the top-3
`hero_id`s (icons only) and discards `games`/`win`. Change: keep
`(hero_id, games, win)` for the top 3, computed as `win/games*100`, shown
as a small percentage + game count under each top-hero icon in
`player_stats_window.py` (e.g. "62% · 12"). Draft row's top-heroes strip
stays icon-only (same reasoning as KDA above — no space).

## 3. Rank/MMR — honest cap

Verified live: `mmr_estimate`, `competitive_rank`, `solo_competitive_rank`
are `None` for a normal (non-leaderboard) account — Valve stopped exposing
exact MMR publicly in 2019. No new number to show for the vast majority of
players. The only additional real field is `leaderboard_rank` (non-null
only for top-tier leaderboard players) — shown as a small "Топ #N" badge
next to the existing rank icon **only when non-null**, nothing added
otherwise. `rank_tier` (already shown as an icon) stays the primary
rank signal.

## 4. Streaks + frequent teammates (OpenDota-sourced, works for anyone)

- **`/players/{id}/peers`** (verified real, returns `account_id`,
  `personaname`, `win`/`games` together, `avatarfull`) - new "Часто играешь
  с" section in `player_stats_window.py` (self-stats only - this endpoint
  is about the queried account's own peers, not meaningful to show on a
  looked-up stranger's profile), top 3 by `games`, each showing avatar +
  name + win/games together.
- **Overall win/loss streak**: not available via public OpenDota
  account-level endpoints - not attempted here. (Per-hero streaks are
  covered by the local `stats.dat` source in section 5 instead.)

## 5. Local `stats.dat` bonus layer (self-stats only)

Confirmed present and already reverse-engineered structurally earlier this
session: `~/.local/share/Steam/userdata/<account_id>/570/remote/cfg/stats.dat`,
same VBKV/binary-KeyValues family as `last_match.dat`, holding a
`hero_standings` array with one block per hero:
`hero_id, wins, losses, win_streak, best_win_streak, avg_kills, avg_deaths,
avg_assists, avg_gpm, avg_xpm, best_kills, best_assists, best_gpm,
best_xpm, wins_with_ally, losses_with_ally, wins_against_enemy,
losses_against_enemy, networth_peak, lasthit_peak, deny_peak, damage_peak,
longest_game_peak, healing_peak, avg_lasthits, avg_denies`.

None of this exists anywhere in public OpenDota - it's local-only, and
loads instantly (no network round-trip, no rate limit).

- **New module `local_hero_stats.py`** (parallel to `last_match_watcher.py`):
  unlike `last_match.dat`'s single-field hack, this file has *many*
  repeated keys (`hero_id`, `wins`, `games`... once per hero block), so the
  byte-offset-search trick from `last_match_watcher.py` does not scale -
  needs an actual binary-KeyValues parser. Uses the `vdf` PyPI package's
  `binary_loads()` (same author as `ValvePython/dota2`, already vetted
  during this session's protocol research) to parse the payload after
  stripping the 8-byte `VBKV` + checksum header. New dependency, added to
  `requirements.txt`.
- **Availability check**: `vdf.binary_loads` support for this exact
  variant is not yet confirmed against the real file - first implementation
  step is a throwaway script parsing the real `stats.dat` already on disk
  and diffing its output against the hand-decoded structure from this
  session's hex-dump work, before wiring it into the app for real.
- **Surfaced in `player_stats_window.py`**, self-stats render path only
  (this file only exists for the locally logged-in account - never shown
  for a looked-up stranger or a last-match-recap opponent): per top-hero,
  a small "Личный рекорд" block - best KDA-adjacent numbers
  (`best_kills`/`best_gpm`/`best_xpm`) and current `win_streak` if nonzero.

## Testing

No automated tests, per this project's standing decision. Manual
verification: self-stats hotkey shows KDA/GPM/XPM per recent match, top
heroes with real win%, peers section, and local stats.dat bests/streaks
for at least one hero with nonzero games; profile-lookup and last-match
recap show KDA/GPM/XPM and top-hero win% (no peers/local-stats section -
those stay self-only); an account with `leaderboard_rank` unavailable
(the common case) shows no "Топ #N" badge, only the existing rank icon;
confirm the new `vdf` dependency actually installs on Arch - exact package
name (AUR vs. pip with `--break-system-packages`, matching this project's
existing install instructions) not yet verified, first implementation step.
