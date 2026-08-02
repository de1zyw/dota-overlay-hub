# Diagnostic event log — design

## Purpose

A per-run diagnostic log the user can hand to Claude after a real match (or any
test run) so Claude can read exactly what happened — which match was detected,
whether stats fetches succeeded, whether GSI pick-matching resolved, when the
overlay showed/hid, and any crashes — without the user needing to describe or
reproduce the issue verbally. This is a **dev-time tool**, not a user-facing
feature: it exists purely to make Claude-assisted debugging possible during
ongoing development.

**Future consideration (not in scope now):** when the installer/launcher task
(already queued, explicitly last in the project's task order) is built, decide
whether to strip this logging entirely for release, or expose it as an opt-in
launcher toggle with a plain-text (not JSON) format for end users. No decision
needed now — this log stays always-on, dev-only, JSON Lines.

## Architecture

New module `event_log.py`, a small dependency-free singleton logger:

- `init(log_dir="logs")` — called once, early in `app.py`. Creates `log_dir`
  if missing, opens a new file `logs/run_<YYYYMMDD_HHMMSS>.jsonl` for the
  process's lifetime. `logs/` is added to `.gitignore` (same treatment as the
  old `gsi_captures.jsonl`).
- `log(event, **fields)` — appends one JSON line: `{"ts": <ISO8601 with ms>,
  "event": <event>, **fields}`. Guarded by a `threading.Lock` (multiple
  threads write: the lobby watcher thread, the GSI HTTP server thread, the Qt
  main thread, pynput's hotkey thread). Never raises — a failed write is
  swallowed silently, matching the "auxiliary code never crashes the app"
  convention already used in `assets.py`/`opendota_client.py`. Before `init()`
  is called, `log()` is a no-op (defensive; in practice `init()` always runs
  first since `app.py` calls it immediately).
- `install_exception_hooks()` — called once from `app.py`. Sets
  `sys.excepthook` (catches unhandled exceptions on the main/Qt thread —
  PyQt6 routes slot exceptions through this hook by default) and
  `threading.excepthook` (catches unhandled exceptions on any
  `threading.Thread`, which covers both the lobby watcher thread and
  pynput's listener thread, since `pynput.keyboard.Listener` itself subclasses
  `threading.Thread`). Both hooks log an `ERROR` event (exception type,
  message, formatted traceback, thread name) and then call through to the
  original hook, so existing stderr output behavior is unchanged.

No other module needs to import `event_log.py` except `app.py` and
`gsi_server.py` (see events below) — this keeps the blast radius small and the
rest of the codebase untouched.

## Events

All medium-granularity, one JSON object per line:

1. **`APP_START`** — `{pid}`. Logged once at the top of `OverlayApp.run()`.
2. **`MATCH_FOUND`** — `{radiant: [account_id...], dire: [account_id...],
   party: [account_id...]}`. Logged in `on_new_match`, right after the roster
   arrives.
3. **`STATS_FETCH`** — one per account_id, `{account_id, nickname, hidden}`.
   Logged in `on_new_match` after `self.executor.map(fetch_player_stats, ...)`
   completes, from the resulting `PlayerStats` objects already in hand — no
   changes needed inside `opendota_client.py` itself. `hidden=True` is the
   existing signal for "fetch didn't yield real stats" (either a genuinely
   hidden profile or an OpenDota failure — not distinguished further, per the
   "medium" detail level, no need for finer granularity here).
4. **`GSI_PAYLOAD`** — `{data: <raw GSI JSON>}`. Logged in `gsi_server.py`'s
   `_on_payload`, replacing the current standalone write to
   `gsi_captures.jsonl` (that file and the `captures_path` constructor param
   are removed — everything folds into the one per-run log, per explicit user
   choice).
5. **`PICK_POLL`** — `{picks: {account_id: hero_id_or_null, ...}}`. Logged in
   `app.py`'s `_poll_picks`, once per tick when `self.match_state` is set
   (every `GSI_POLL_INTERVAL_SECONDS`, currently 2s, for as long as a match is
   tracked — this runs even while the overlay is auto-hidden, matching
   existing behavior; not changing that here).
6. **`OVERLAY_SHOW`** / **`OVERLAY_HIDE`** — `{reason: "new_match" |
   "auto_hide" | "hotkey"}`. Logged in `_MainThreadBridge`'s
   `_on_new_match_ready` (show, reason `new_match`), a new small bridge slot
   wired to `hide_timer.timeout` instead of connecting straight to
   `window.hide_overlay` (hide, reason `auto_hide`), and `_on_toggle_visibility`
   (both directions, reason `hotkey`).
7. **`HOTKEY`** — `{action: "toggle" | "expand"}`. Logged in
   `_on_toggle_visibility` / `_on_expand`.
8. **`ERROR`** — `{where: "excepthook" | "threading_excepthook", exc_type,
   message, traceback, thread_name}`. Logged by the two hooks installed via
   `install_exception_hooks()`.

## Error handling

Every `event_log.log()` call is itself wrapped so a logging failure (disk
full, permissions) can never crash the app or interrupt the feature it's
observing — consistent with the rest of the codebase's "auxiliary failure is
silent, core feature keeps working" convention.

## Testing

No automated tests, per this project's standing decision — manual
verification only (run `run_demo.py`, confirm `logs/run_*.jsonl` is created
and populated with the expected event sequence as the demo match is
detected/shown/hidden), same process used for all 18 prior tasks.
