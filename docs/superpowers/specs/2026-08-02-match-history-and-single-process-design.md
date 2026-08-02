# Match IDs in history + single-process hub — design

Two independent improvements requested together; bot integration is
explicitly deferred to a separate future brainstorm.

## Feature A: Match IDs in profile-lookup history

Currently `profile_lookup_history.json` stores only `{account_id,
nickname, timestamp}` per lookup. Add each lookup's recent match IDs so
the ИСТОРИЯ page can link straight to a match on Dotabuff/OpenDota — no
bot involvement, just links, matching what `dota_stats_bot` already does
for its own `/vs <match_id>` command (reusing the *idea*, not its code).

- **`opendota_client.PlayerStats.recent_matches`** grows from `(hero_id,
  won)` 2-tuples to `(hero_id, won, match_id)` 3-tuples — the real
  OpenDota `recentMatches` response already includes `match_id`, just
  wasn't kept before. `overlay_window._match_history_group`'s unpacking
  loop updates to 3 values (match_id unused there, only needed by the
  history feature) — this is the only other place that unpacks the tuple
  shape directly.
- **`profile_lookup_history.append(account_id, nickname, match_ids)`**
  gains a third required param, storing `match_ids: list[int]` per entry.
  `app.py`'s `_show_profile` passes `[m[2] for m in stats.recent_matches]`.
- **Hub's ИСТОРИЯ page** becomes a two-pane list+detail view (mirroring
  the existing ЛОГИ page's layout): left list of past lookups (nickname +
  timestamp), right detail pane shows the selected entry's match IDs as
  real clickable links (`https://www.dotabuff.com/matches/<id>`) via
  `QLabel` rich text + `setOpenExternalLinks(True)`.

## Feature B: Hub and overlay merge into one process

Today `launcher.py` (hub) and `app.py` (overlay) are two separate
`QApplication`s/processes — clicking "Запустить" spawns `app.py` as a
subprocess and closes the hub. The user wants one process instead.

- **`OverlayApp` stops owning `QApplication`.** Remove `self.qt_app =
  QApplication(sys.argv)` and its `setWindowIcon` call from
  `OverlayApp.__init__` — a `QApplication` must already exist by the time
  `OverlayApp` is constructed (Qt allows exactly one per process).
  `app.py`'s own `if __name__ == "__main__":` block still works
  standalone: it creates the `QApplication` itself *before* constructing
  `OverlayApp`, preserving today's "run app.py directly for a quick test"
  workflow.
- **`OverlayApp.run()` splits into `start_services()` + `run()`.**
  `start_services()` is everything `run()` used to do except the final
  `sys.exit(self.qt_app.exec())` — starting GSI, hotkeys, the watcher
  thread, the pick-timer. `run()` (standalone use) calls
  `start_services()` then enters the event loop and exits on close, same
  as today.
- **`LauncherWindow` owns a lazily-created `OverlayApp`.** Clicking
  "Запустить" on *any* of the 3 overlay cards (they already all share
  `entry_script="app.py"` — same running process, not separate scripts)
  calls `LauncherWindow.start_overlay_and_hide()`: constructs `OverlayApp`
  once (a guard prevents starting it twice if already running from an
  earlier Launch click) and calls `.start_services()` — all within the
  hub's own already-running event loop — then hides the hub window
  instead of quitting the app. Requires threading an `on_launch` callback
  from `LauncherWindow` → `_OverlaysPage` → `_OverlayCard` (currently
  `_OverlayCard._on_launch` calls `subprocess.Popen(...)` +
  `QApplication.instance().quit()` directly; both become a single call to
  the passed-in callback instead).
- **System tray icon** (the Dire `icon.png`, already used for the window
  icon) stays present for the process's whole lifetime once the hub
  window is constructed. Left-click toggles the hub window
  show/hide; right-click context menu has "Открыть хаб" and "Выйти" (the
  only real quit path now, since there's no separate process to just
  close a terminal on). The hub window's own close (X) button hides to
  tray instead of quitting, consistent with "the overlay might still be
  running in the background" — same reasoning as why Launch hides rather
  than closes.
- **Out of scope for this change:** `dota_stats_bot` integration (separate
  future brainstorm, per explicit user request); any change to how the
  overlay/self-stats/profile-lookup features themselves work internally.

## Testing

No automated tests, per this project's standing decision — manual
verification only: confirm `recent_matches` 3-tuples propagate correctly
end-to-end (draft rows still render, history page shows real match IDs
as clickable links); confirm clicking Launch from the hub starts the
overlay's services *without* spawning a second process, hides the hub
window, and the tray icon appears and can bring the hub back; confirm
`app.py` run directly (no hub) still works standalone unchanged.
