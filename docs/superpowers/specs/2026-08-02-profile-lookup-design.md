# Profile lookup (OCR-based) — design

## Purpose

Revives "sub-project 3" from the original brainstorm: press a hotkey while
viewing **any** player's profile screen in Dota's client (friends list,
post-match screen, someone else's replay — not just your current
match/draft), and see that player's OpenDota stats. Unlike the draft
overlay and self-stats (both backed by clean structured data — files,
JSON, VDF), there is **no known legal API or local file** that reveals
which profile is currently open in Dota's UI — confirmed via research this
session: Overwolf's Dota 2 companion apps (DotaPlus, Enemy Stats) run on
the same public GSI feed this project already uses (their own docs require
the same `-gamestateintegration` launch flag), not some hidden channel,
and GSI itself only ever exposes the *local client's own* data during a
live match — never menu/profile-browsing state. The only remaining legal
approach is **OCR**: read the nickname directly off the screen.

**Honest reliability caveat, stated up front:** this is fundamentally less
reliable than every other feature in this project. It depends on screen
capture actually seeing the game content (works when Dota runs
fullscreen-windowed, which is the Linux default — true exclusive
fullscreen could block it, untested), on the calibrated screen region
still lining up (breaks if resolution/UI scale changes), on OCR reading
the nickname correctly (game fonts, stylized names, non-Latin scripts),
and on OpenDota's nickname search actually finding the right account
(nicknames aren't unique). Every stage can fail; the design surfaces
failures clearly rather than silently guessing.

## Pipeline

1. **Region calibration (one-time setup, redo if resolution changes):** a
   new hotkey (default `<ctrl>+<alt>+r`) shows a fullscreen transparent
   overlay. Pressed while a real Dota profile screen is visible (Dota
   still rendering behind the overlay — this only works because Linux
   Dota typically runs fullscreen-*windowed*, not exclusive fullscreen),
   the user click-drags a rectangle around the nickname text. The
   rectangle (screen-absolute `x, y, width, height`) is saved to
   `profile_lookup_settings.json` via a new `profile_lookup_settings.py`
   (`load()`/`save()`, same never-raises pattern as `hotkey_settings.py`).
2. **Lookup (on demand):** a second new hotkey (default `<ctrl>+<alt>+p`)
   triggers, in order: screen-capture the calibrated region (`mss`
   library) → OCR the text (`pytesseract`, wrapping the system `tesseract`
   binary) → clean up the raw text (strip whitespace/newlines) → search
   OpenDota's `/players/{account_id}` — actually `/search?q=<name>`
   endpoint (new function in `opendota_client.py`) for candidate accounts.
3. **Disambiguation:** OpenDota's name search can return multiple
   accounts (nicknames aren't unique). A new small window lists the top 5
   candidates (avatar + nickname), the user clicks the right one. Exactly
   one result skips straight to step 4; zero results shows "профиль не
   распознан/не найден" instead of guessing.
4. **Display:** the chosen account's stats render in the *same* window
   class used for self-stats — renamed from `SelfStatsWindow` to
   `PlayerStatsWindow` (its `render_stats(stats)` was already generic, not
   self-specific; only `app.py`'s `on_self_stats_hotkey` decided *whose*
   stats to fetch). `app.py` now holds one instance used by both the
   self-stats and profile-lookup hotkeys.
5. **History:** every successful selection (nickname, account_id,
   timestamp) appends to `profile_lookup_history.json` via a new
   `profile_lookup_history.py` (`append(entry)`/`load_all()`). A new
   **"ИСТОРИЯ"** page in the hub lists past lookups (newest first,
   nickname + timestamp), clicking a row re-fetches and shows that
   account's current stats without redoing OCR.

## New dependencies

- **pip** (`requirements.txt`): `mss` (screen capture), `pytesseract`
  (OCR wrapper).
- **System package, NOT pip-installable** (the launcher cannot install
  this itself): the `tesseract` binary. New hard-blocker check in
  `launcher_checks.py` (`check_tesseract`) — checks `shutil.which("tesseract")`,
  and if missing, shows the exact install command for the user's distro:
  `sudo pacman -S tesseract tesseract-data-rus` (their real Dota machine is
  Arch/CachyOS).

## Hub changes

- "Профиль по клику" moves from `COMING_SOON_ENTRIES` to a real
  `OVERLAY_ENTRIES` card (same `entry_script: "app.py"` as the other two —
  it's hotkeys inside the same running process, not a separate script),
  with its own checklist: Python deps, tesseract installed (hard
  blocker), and whether a region has been calibrated yet (warning, not
  blocker — the feature just won't do anything useful until calibrated,
  same "report don't auto-fix" philosophy as everything else in this hub).
- New **"ИСТОРИЯ"** sidebar page (4th nav entry) showing
  `profile_lookup_history.py`'s log.

## Testing

No automated tests, per this project's standing decision — manual
verification only: calibrate against a real or mocked profile screen
region, confirm the saved region round-trips through
`profile_lookup_settings.json`; feed a known clear screenshot through the
OCR+search pipeline and confirm candidates surface correctly; confirm the
zero-match and multiple-match paths both behave as designed (clear
message vs. picker list) rather than crashing or guessing silently;
confirm history entries persist and are clickable from the hub.
