# Diagnostic Event Log Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a per-run JSON-Lines diagnostic log that captures match detection, stats fetches, GSI payloads, pick-poll results, overlay show/hide, hotkeys, and unhandled exceptions, so the user can hand a log file to Claude after a real match for debugging.

**Architecture:** A new dependency-free `event_log.py` module owns a single append-only JSONL file per process run (`logs/run_<timestamp>.jsonl`) behind a thread-safe, never-raising `log(event, **fields)` call, plus global exception hooks. `app.py` calls it at the specific points listed in the spec; `gsi_server.py` calls it instead of writing its own separate capture file (which is removed).

**Tech Stack:** Python stdlib only (`json`, `threading`, `datetime`, `sys`, `traceback`, `os`) — no new dependencies.

## Global Constraints

- No automated tests for this project (standing decision) — every task is verified manually by running the app and inspecting the resulting log file, same process used for all prior tasks in this codebase.
- `event_log.log()` must never raise — a logging failure must never crash the app or interrupt the feature it's observing.
- Logging must be thread-safe: writers include the Qt main thread, the lobby watcher background thread, the GSI HTTP server thread, and pynput's hotkey listener thread.
- One file per process run, JSON Lines format, each line `{"ts": <ISO8601 with milliseconds>, "event": <name>, ...fields}`.
- `logs/` directory must be added to `.gitignore`.
- This is a dev-only tool — no config flag, no toggle, always on. (Release-time behavior is out of scope, deferred to the installer/launcher task.)

---

### Task 1: `event_log.py` module

**Files:**
- Create: `event_log.py`
- Modify: `.gitignore` (add `logs/`)

**Interfaces:**
- Produces:
  - `event_log.init(log_dir="logs")` — creates `log_dir` if missing, opens `<log_dir>/run_<YYYYMMDD_HHMMSS>.jsonl` for append, stores the open path/handle in module state. Safe to call more than once (a second call just reuses whatever is already open — no need to reopen a new file mid-run).
  - `event_log.log(event, **fields)` — writes one JSON line `{"ts": iso_ts, "event": event, **fields}` to the current run's file. No-op (silently) if `init()` was never called. Never raises under any failure (disk full, permissions, non-JSON-serializable field, etc).
  - `event_log.install_exception_hooks()` — sets `sys.excepthook` and `threading.excepthook` to wrapper functions that call `event_log.log("ERROR", where=..., exc_type=..., message=..., traceback=..., thread_name=...)` and then delegate to whatever hook was previously installed (so existing stderr output is unchanged).

- [ ] **Step 1: Write `event_log.py`**

```python
"""Per-run JSON-Lines diagnostic log. Purely a dev-time debugging aid: the
user hands the resulting logs/run_*.jsonl file to Claude after a real match
so it can be read directly instead of the user describing what happened.
Never raises - a logging failure must never interrupt the feature it's
observing (same convention as assets.py/opendota_client.py)."""
import json
import os
import sys
import threading
import traceback
from datetime import datetime, timezone

_lock = threading.Lock()
_file = None


def init(log_dir="logs"):
    global _file
    with _lock:
        if _file is not None:
            return
        try:
            os.makedirs(log_dir, exist_ok=True)
            ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            path = os.path.join(log_dir, f"run_{ts}.jsonl")
            _file = open(path, "a", encoding="utf-8")
        except OSError:
            _file = None


def log(event, **fields):
    with _lock:
        if _file is None:
            return
        try:
            line = {
                "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                "event": event,
                **fields,
            }
            _file.write(json.dumps(line, default=str) + "\n")
            _file.flush()
        except (OSError, TypeError, ValueError):
            pass


def _log_exception(where, exc_type, exc_value, exc_tb, thread_name):
    log(
        "ERROR",
        where=where,
        exc_type=exc_type.__name__ if exc_type else None,
        message=str(exc_value),
        traceback="".join(traceback.format_exception(exc_type, exc_value, exc_tb)),
        thread_name=thread_name,
    )


def install_exception_hooks():
    previous_excepthook = sys.excepthook
    previous_threading_excepthook = threading.excepthook

    def _excepthook(exc_type, exc_value, exc_tb):
        _log_exception("excepthook", exc_type, exc_value, exc_tb, threading.current_thread().name)
        previous_excepthook(exc_type, exc_value, exc_tb)

    def _threading_excepthook(args):
        _log_exception(
            "threading_excepthook", args.exc_type, args.exc_value, args.exc_traceback,
            args.thread.name if args.thread else "unknown",
        )
        previous_threading_excepthook(args)

    sys.excepthook = _excepthook
    threading.excepthook = _threading_excepthook
```

- [ ] **Step 2: Add `logs/` to `.gitignore`**

Add a line `logs/` to `/home/de1zyw/dota_overlay/.gitignore` (alongside the existing `.assets_cache/` entry).

- [ ] **Step 3: Manual verification**

Run:
```bash
cd /home/de1zyw/dota_overlay
python3 -c "
import event_log
event_log.init()
event_log.log('APP_START', pid=1234)
event_log.log('MATCH_FOUND', radiant=[1,2,3], dire=[4,5,6])
"
ls logs/
cat logs/run_*.jsonl
```
Expected: `logs/` contains exactly one `run_<timestamp>.jsonl` file, and it contains two JSON lines, each with a valid ISO `ts`, the right `event` name, and the right fields.

Then verify the exception hooks don't crash the app and do log:
```bash
python3 -c "
import event_log
event_log.init()
event_log.install_exception_hooks()
raise ValueError('test crash')
"
cat logs/run_*.jsonl
```
Expected: the process exits with the usual Python traceback printed to stderr (unchanged behavior), AND the same run's log file gains an `ERROR` line with `where=excepthook`, `exc_type=ValueError`, `message=test crash`, and a populated `traceback` field.

- [ ] **Step 4: Commit**

```bash
git add event_log.py .gitignore
git commit -m "feat: add per-run JSONL diagnostic event log module"
```

---

### Task 2: Wire event logging into `app.py` and `gsi_server.py`

**Files:**
- Modify: `app.py`
- Modify: `gsi_server.py`

**Interfaces:**
- Consumes: `event_log.init()`, `event_log.log(event, **fields)`, `event_log.install_exception_hooks()` from Task 1.

- [ ] **Step 1: Wire `app.py`**

In `app.py`, add `import event_log` near the top, alongside the other local imports.

In `OverlayApp.run()`, at the very top (before `self.gsi.start()`), add:
```python
event_log.init()
event_log.install_exception_hooks()
event_log.log("APP_START", pid=os.getpid())
```
(add `import os` at the top of `app.py` if not already present — it is not currently imported).

In `on_new_match`, right after `stats_by_id = dict(...)` is built and `radiant`/`dire` are computed, add (roster tuples are `(team, slot, account_id)`):
```python
event_log.log(
    "MATCH_FOUND",
    radiant=[aid for team, _, aid in roster if team == "radiant"],
    dire=[aid for team, _, aid in roster if team == "dire"],
    party=sorted(party_account_ids),
)
for stats in stats_by_id.values():
    event_log.log("STATS_FETCH", account_id=stats.account_id, nickname=stats.nickname, hidden=stats.hidden)
```
Place the `MATCH_FOUND` call right after `stats_by_id` is computed (so account IDs are available) and the `STATS_FETCH` loop right after it, both before `current_picks = match_current_picks(...)`.

In `_poll_picks`, after `current_picks = match_current_picks(state.roster, self.gsi.latest_raw)`, add:
```python
event_log.log("PICK_POLL", picks=current_picks)
```

In `_MainThreadBridge.__init__`, change the `hide_timer.timeout` wiring so it goes through a new bridge method instead of connecting straight from `OverlayApp.__init__`. Concretely, in `OverlayApp.__init__`, change:
```python
self.hide_timer.timeout.connect(self.window.hide_overlay)
```
to:
```python
self.hide_timer.timeout.connect(lambda: self.bridge.on_auto_hide())
```
(this line currently runs before `self.bridge` is constructed — move the `self.hide_timer.timeout.connect(...)` line to after `self.bridge = _MainThreadBridge(...)` is constructed, keeping `self.hide_timer.setSingleShot(True)` where it is).

Add a new method to `_MainThreadBridge`:
```python
def on_auto_hide(self):
    event_log.log("OVERLAY_HIDE", reason="auto_hide")
    self._window.hide_overlay()
```

In `_MainThreadBridge._on_new_match_ready`, add a log call before showing:
```python
def _on_new_match_ready(self, radiant, dire, current_picks, party_account_ids):
    self._window.render_lobby(radiant, dire, current_picks, party_account_ids)
    event_log.log("OVERLAY_SHOW", reason="new_match")
    self._window.show_overlay()
    self._hide_timer.start(config.AUTO_HIDE_SECONDS * 1000)
```

In `_MainThreadBridge._on_toggle_visibility`, add logging for both directions:
```python
def _on_toggle_visibility(self):
    event_log.log("HOTKEY", action="toggle")
    if self._window.isVisible():
        event_log.log("OVERLAY_HIDE", reason="hotkey")
        self._window.hide_overlay()
    else:
        event_log.log("OVERLAY_SHOW", reason="hotkey")
        self._window.show_overlay()
```

In `_MainThreadBridge._on_expand`, add:
```python
def _on_expand(self):
    event_log.log("HOTKEY", action="expand")
    self._window.toggle_expanded()
```

- [ ] **Step 2: Wire `gsi_server.py`**

In `gsi_server.py`, add `import event_log` near the top and remove the `import json`-based file write. Change `GSIServer.__init__` to drop the `captures_path` parameter entirely:
```python
def __init__(self, host, port):
    self.host = host
    self.port = port
    self.latest_raw = None
    self._lock = threading.Lock()
    self._httpd = None
    self._thread = None
```
Change `_on_payload`:
```python
def _on_payload(self, data):
    with self._lock:
        self.latest_raw = data
    event_log.log("GSI_PAYLOAD", data=data)
```
The module's `json` import is still needed (for `json.loads(body)` in `_Handler.do_POST`) — only the write-to-file usage is removed.

`app.py` already constructs `GSIServer(config.GSI_HOST, config.GSI_PORT)` with no `captures_path` argument, so no call-site change is needed there.

- [ ] **Step 3: Manual verification**

```bash
cd /home/de1zyw/dota_overlay
rm -f /tmp/my_test_log.txt
cp fixtures/server_log_sample.txt /tmp/my_test_log.txt
python3 run_demo.py &
sleep 3
kill %1 2>/dev/null
cat logs/run_*.jsonl | tail -20
```
Expected: the newest `logs/run_*.jsonl` contains, in order, an `APP_START` line, a `MATCH_FOUND` line with 5 `radiant` and 5 `dire` account IDs and a `party` list, 10 `STATS_FETCH` lines (one per account_id), and at least one `OVERLAY_SHOW` line with `reason="new_match"`. Confirm no `gsi_captures.jsonl` file is created anywhere in the repo root during this run (the old capture file is fully replaced by `GSI_PAYLOAD` events in the same log).

Also confirm the app still renders and shows the overlay exactly as before this change (no visual regression) — run it and glance at the window like in prior tasks.

- [ ] **Step 4: Commit**

```bash
git add app.py gsi_server.py
git commit -m "feat: log match/stats/pick/overlay/hotkey events to the diagnostic log"
```
