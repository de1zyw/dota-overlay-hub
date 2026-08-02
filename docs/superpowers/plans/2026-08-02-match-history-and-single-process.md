# Match IDs in History + Single-Process Hub Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show match IDs (as clickable Dotabuff links) in the profile-lookup history, and merge the hub and overlay into one process with a system tray icon instead of a subprocess-launch-and-quit.

**Architecture:** `PlayerStats.recent_matches` grows a `match_id` field, threaded through to `profile_lookup_history.append()` and rendered in a two-pane История page (mirroring the existing Logs page). Separately, `OverlayApp` stops owning `QApplication` and splits `run()` into `start_services()` + `run()`; the hub constructs `OverlayApp` in-process on Launch and hides to a `QSystemTrayIcon` instead of spawning `app.py` as a subprocess and quitting.

**Tech Stack:** Existing PyQt6/`requests` only — no new dependencies.

## Global Constraints

- No automated tests for this project (standing decision) — manual verification only.
- Old `profile_lookup_history.json` entries (written before this change, no `match_ids` key) must not crash the История page — use `.get("match_ids") or []`.
- Exactly one `QApplication` may exist per process — `OverlayApp` must never construct one; whichever entry point runs first (`launcher.py`, or `app.py` standalone) owns it.
- `app.py` run directly (`python3 app.py`, no hub) must keep working exactly as before — standalone use is not being removed.
- Bot integration with `~/dota_stats_bot` is explicitly out of scope for this plan (separate future brainstorm).

---

### Task 1: `match_id` in `recent_matches`

**Files:**
- Modify: `opendota_client.py`
- Modify: `overlay_window.py`

**Interfaces:**
- Produces: `PlayerStats.recent_matches` is now `list[tuple[int, bool, int]]` — `(hero_id, won, match_id)`, newest first, max 10 (was `(hero_id, won)` 2-tuples).

- [ ] **Step 1: Add `match_id` to the tuple in `opendota_client.py`**

Change:
```python
    recent_matches: list = field(default_factory=list)  # [(hero_id, won: bool), ...], newest first, max 10
```
to:
```python
    recent_matches: list = field(default_factory=list)  # [(hero_id, won: bool, match_id: int), ...], newest first, max 10
```

Change:
```python
    recent_matches = [
        (m.get("hero_id"), m.get("radiant_win") == (m.get("player_slot", 0) < 128))
        for m in recent[:10]
    ]
```
to:
```python
    recent_matches = [
        (m.get("hero_id"), m.get("radiant_win") == (m.get("player_slot", 0) < 128), m.get("match_id"))
        for m in recent[:10]
    ]
```

- [ ] **Step 2: Update the one place that unpacks the tuple - `overlay_window.py`'s `_match_history_group`**

Change:
```python
    for hero_id, won in recent_matches[:MATCH_HISTORY_COUNT]:
```
to:
```python
    for hero_id, won, _match_id in recent_matches[:MATCH_HISTORY_COUNT]:
```
(`match_id` isn't used in this draft-row rendering - prefixed with `_` per convention for an intentionally-unused unpacked value.)

- [ ] **Step 3: Manual verification**

```bash
cd /home/de1zyw/dota_overlay
python3 -c "
from opendota_client import fetch_player_stats
stats = fetch_player_stats(111620041)
print(len(stats.recent_matches), 'matches')
for hero_id, won, match_id in stats.recent_matches[:3]:
    print(hero_id, won, match_id)
"
python3 -c "import ast; ast.parse(open('overlay_window.py').read())" && echo "overlay_window.py syntax OK"
```
Expected: 3 sample rows print with a real, non-`None` `match_id` for each (a real numeric Dota match ID); syntax check passes.

- [ ] **Step 4: Commit**

```bash
git add opendota_client.py overlay_window.py
git commit -m "feat: include match_id in recent_matches"
```

---

### Task 2: Store match IDs in profile-lookup history

**Files:**
- Modify: `profile_lookup_history.py`
- Modify: `app.py`

**Interfaces:**
- Consumes: `PlayerStats.recent_matches` 3-tuples (Task 1).
- Produces: `profile_lookup_history.append(account_id, nickname, match_ids)` (new required 3rd param, `list[int]`); each stored entry gains a `match_ids` key.

- [ ] **Step 1: Update `profile_lookup_history.append`**

Change:
```python
def append(account_id, nickname):
    entries = load_all()
    entries.insert(0, {
        "account_id": account_id,
        "nickname": nickname,
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    })
```
to:
```python
def append(account_id, nickname, match_ids):
    entries = load_all()
    entries.insert(0, {
        "account_id": account_id,
        "nickname": nickname,
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "match_ids": match_ids,
    })
```

- [ ] **Step 2: Update the call site in `app.py`**

Change:
```python
        stats = fetch_player_stats(account_id)
        self._player_stats_window.render_stats(stats)
        self._player_stats_window.show_stats()
        profile_lookup_history.append(account_id, stats.nickname)
```
to:
```python
        stats = fetch_player_stats(account_id)
        self._player_stats_window.render_stats(stats)
        self._player_stats_window.show_stats()
        match_ids = [match_id for _, _, match_id in stats.recent_matches if match_id is not None]
        profile_lookup_history.append(account_id, stats.nickname, match_ids)
```

- [ ] **Step 3: Manual verification**

```bash
cd /home/de1zyw/dota_overlay
rm -f profile_lookup_history.json
python3 -c "
import profile_lookup_history as h
h.append(111620041, 'Miracle-', [8261263481, 8260123456])
for entry in h.load_all():
    print(entry)
"
rm -f profile_lookup_history.json
python3 -c "import ast; ast.parse(open('app.py').read())" && echo "app.py syntax OK"
```
Expected: the printed entry includes a `match_ids` key with the 2 sample IDs; syntax check passes.

- [ ] **Step 4: Commit**

```bash
git add profile_lookup_history.py app.py
git commit -m "feat: store match IDs with each profile-lookup history entry"
```

---

### Task 3: История page shows clickable match links

**Files:**
- Modify: `launcher.py`

**Interfaces:**
- Consumes: `profile_lookup_history.load_all()`'s entries now carrying `match_ids` (Task 2, gracefully absent on old entries via `.get`).

- [ ] **Step 1: Rewrite `_HistoryPage` as a two-pane list+detail view**

Replace the entire `_HistoryPage` class with:
```python
class _HistoryPage(QWidget):
    def __init__(self):
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        self._list = QListWidget()
        self._list.setFixedWidth(260)
        self._list.setStyleSheet(
            "QListWidget { background-color: rgba(255,255,255,10); color: white; "
            "font-family: sans-serif; font-size: 12px; border: none; border-radius: 6px; }"
            "QListWidget::item { padding: 6px; }"
            "QListWidget::item:selected { background-color: rgba(255,255,255,30); }"
        )
        self._list.currentRowChanged.connect(self._on_row_changed)
        layout.addWidget(self._list)

        self._detail = QLabel("Выбери запись слева")
        self._detail.setWordWrap(True)
        self._detail.setTextFormat(Qt.TextFormat.RichText)
        self._detail.setOpenExternalLinks(True)
        self._detail.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._detail.setStyleSheet("color: white; font-family: sans-serif; font-size: 12px;")
        layout.addWidget(self._detail, 1)

        self._entries = []
        self.refresh()

    def refresh(self):
        self._entries = profile_lookup_history.load_all()
        self._list.clear()
        if not self._entries:
            self._detail.setText("Пока пусто — история появится после первого использования «Профиль по клику»")
            return
        for entry in self._entries:
            self._list.addItem(f"{entry['timestamp']}  —  {entry['nickname']}")
        self._list.setCurrentRow(0)

    def _on_row_changed(self, row):
        if row < 0 or row >= len(self._entries):
            return
        entry = self._entries[row]
        lines = [f"<b>{entry['nickname']}</b>", entry["timestamp"], "", "Матчи:"]
        match_ids = entry.get("match_ids") or []
        if not match_ids:
            lines.append("(нет данных о матчах)")
        else:
            for match_id in match_ids:
                lines.append(f'<a href="https://www.dotabuff.com/matches/{match_id}">{match_id}</a>')
        self._detail.setText("<br>".join(lines))
```

- [ ] **Step 2: Manual verification**

```bash
cd /home/de1zyw/dota_overlay
python3 -c "import ast; ast.parse(open('launcher.py').read())" && echo "syntax OK"
rm -f profile_lookup_history.json
python3 -c "
import profile_lookup_history as h
h.append(111620041, 'Miracle-', [8261263481, 8260123456])
"
python3 -c "
import sys
from PyQt6.QtWidgets import QApplication
from launcher import _HistoryPage
app = QApplication(sys.argv)
page = _HistoryPage()
print('list item count:', page._list.count())
page._list.setCurrentRow(0)
print('detail html:', page._detail.text())
"
rm -f profile_lookup_history.json
```
Expected: syntax OK; list item count is 1; detail HTML contains the nickname, timestamp, and 2 `<a href="https://www.dotabuff.com/matches/...">` links with the sample match IDs.

- [ ] **Step 3: Commit**

```bash
git add launcher.py
git commit -m "feat: show clickable match links in the История page"
```

---

### Task 4: `OverlayApp` stops owning `QApplication`

**Files:**
- Modify: `app.py`

**Interfaces:**
- Produces: `OverlayApp.start_services()` (new method - starts GSI/hotkeys/watcher-thread/pick-timer, everything `run()` used to do except entering the event loop); `OverlayApp.run()` now calls `start_services()` then `sys.exit(QApplication.instance().exec())`. `OverlayApp()` no longer constructs a `QApplication` - the caller must ensure one already exists.

- [ ] **Step 1: Remove `QApplication` construction from `OverlayApp.__init__`**

Change:
```python
class OverlayApp:
    def __init__(self):
        self.qt_app = QApplication(sys.argv)
        self.qt_app.setWindowIcon(QIcon(os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.png")))
        self.window = OverlayWindow()
```
to:
```python
class OverlayApp:
    def __init__(self):
        self.window = OverlayWindow()
```

- [ ] **Step 2: Split `run()` into `start_services()` + `run()`**

Change:
```python
    def run(self):
        event_log.init()
        event_log.install_exception_hooks()
        event_log.log("APP_START", pid=os.getpid())

        self.gsi.start()
        self.hotkeys.start()
        self.pick_timer.start(int(config.GSI_POLL_INTERVAL_SECONDS * 1000))

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
to:
```python
    def start_services(self):
        event_log.init()
        event_log.install_exception_hooks()
        event_log.log("APP_START", pid=os.getpid())

        self.gsi.start()
        self.hotkeys.start()
        self.pick_timer.start(int(config.GSI_POLL_INTERVAL_SECONDS * 1000))

        watcher_thread = threading.Thread(
            target=watch_for_new_match,
            args=(config.SERVER_LOG_PATH, self.on_new_match, config.POLL_INTERVAL_SECONDS),
            daemon=True,
        )
        watcher_thread.start()

    def run(self):
        self.start_services()
        sys.exit(QApplication.instance().exec())


if __name__ == "__main__":
    qt_app = QApplication(sys.argv)
    qt_app.setWindowIcon(QIcon(os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.png")))
    OverlayApp().run()
```

- [ ] **Step 3: Manual verification**

```bash
cd /home/de1zyw/dota_overlay
python3 -c "import ast; ast.parse(open('app.py').read())" && echo "syntax OK"
python3 -c "import app; print('imports cleanly, OverlayApp has start_services:', hasattr(app.OverlayApp, 'start_services'))"
cp fixtures/server_log_sample.txt /tmp/my_test_log.txt
DISPLAY=:0 QT_QPA_PLATFORM=xcb timeout 15 python3 run_demo.py
```
Expected: syntax OK; `start_services` exists on the class; `run_demo.py` (which calls `OverlayApp().run()` standalone, unchanged) still runs for the full 15s with no crash - confirming standalone use still works exactly as before.

- [ ] **Step 4: Commit**

```bash
rm -f /tmp/my_test_log.txt
git add app.py
git commit -m "refactor: split OverlayApp.run() into start_services()+run(), stop owning QApplication"
```

---

### Task 5: Hub launches the overlay in-process, hides to a tray icon

**Files:**
- Modify: `launcher.py`

**Interfaces:**
- Consumes: `OverlayApp`, `OverlayApp.start_services()` (Task 4).
- Produces: `_OverlayCard(entry, on_launch)` (new required 2nd param), `_OverlaysPage(on_launch)` (new required param), `LauncherWindow.start_overlay_and_hide()`.

- [ ] **Step 1: Add `QMenu`/`QSystemTrayIcon` to imports**

Add `QMenu` and `QSystemTrayIcon` to the existing `from PyQt6.QtWidgets import (...)` block in `launcher.py` (alphabetically among the existing names).

- [ ] **Step 2: Thread `on_launch` through `_OverlayCard` and `_OverlaysPage`**

Change:
```python
class _OverlayCard(QWidget):
    def __init__(self, entry):
        super().__init__()
        self._entry = entry
```
to:
```python
class _OverlayCard(QWidget):
    def __init__(self, entry, on_launch):
        super().__init__()
        self._entry = entry
        self._on_launch_callback = on_launch
```

Change:
```python
    def _on_launch(self):
        subprocess.Popen([sys.executable, self._entry["entry_script"]], cwd=PROJECT_DIR)
        QApplication.instance().quit()
```
to:
```python
    def _on_launch(self):
        self._on_launch_callback()
```

Change:
```python
class _OverlaysPage(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        for entry in OVERLAY_ENTRIES:
            layout.addWidget(_OverlayCard(entry))
        for entry in COMING_SOON_ENTRIES:
            layout.addWidget(_ComingSoonCard(entry))
        layout.addStretch()
```
to:
```python
class _OverlaysPage(QWidget):
    def __init__(self, on_launch):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        for entry in OVERLAY_ENTRIES:
            layout.addWidget(_OverlayCard(entry, on_launch))
        for entry in COMING_SOON_ENTRIES:
            layout.addWidget(_ComingSoonCard(entry))
        layout.addStretch()
```

- [ ] **Step 3: Add the tray icon, lazy `OverlayApp`, and `closeEvent` override to `LauncherWindow`**

Change:
```python
        self._overlays_page = _OverlaysPage()
        self._logs_page = _LogsPage()
```
to:
```python
        self._overlay_app = None
        self._overlays_page = _OverlaysPage(on_launch=self.start_overlay_and_hide)
        self._logs_page = _LogsPage()
```

Add these new methods to `LauncherWindow` (anywhere in the class, e.g. right after `_switch_page`):
```python
    def start_overlay_and_hide(self):
        if self._overlay_app is None:
            from app import OverlayApp
            self._overlay_app = OverlayApp()
            self._overlay_app.start_services()
        self.hide()

    def closeEvent(self, event):
        event.ignore()
        self.hide()

    def _setup_tray_icon(self):
        self._tray_icon = QSystemTrayIcon(QIcon(os.path.join(PROJECT_DIR, "icon.png")), self)
        tray_menu = QMenu()
        show_action = tray_menu.addAction("Открыть хаб")
        show_action.triggered.connect(self._show_from_tray)
        quit_action = tray_menu.addAction("Выйти")
        quit_action.triggered.connect(QApplication.instance().quit)
        self._tray_icon.setContextMenu(tray_menu)
        self._tray_icon.activated.connect(self._on_tray_activated)
        self._tray_icon.show()

    def _show_from_tray(self):
        self.show()
        self.raise_()
        self.activateWindow()

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            if self.isVisible():
                self.hide()
            else:
                self._show_from_tray()
```

Call `self._setup_tray_icon()` at the end of `LauncherWindow.__init__` (after `panel_layout.addWidget(content)`, the last line currently in `__init__`).

- [ ] **Step 4: Set `quitOnLastWindowClosed(False)` in `__main__`**

Change:
```python
if __name__ == "__main__":
    app = QApplication(sys.argv)
    # Ties this running process to dota-overlay-hub.desktop by name, so the
    # taskbar/dock can look up that entry's Icon= instead of falling back to
    # a generic icon when it can't otherwise correlate the window to it.
    app.setDesktopFileName("dota-overlay-hub")
    app.setWindowIcon(QIcon(os.path.join(PROJECT_DIR, "icon.png")))
    window = LauncherWindow()
    window.show()
    sys.exit(app.exec())
```
to:
```python
if __name__ == "__main__":
    app = QApplication(sys.argv)
    # Ties this running process to dota-overlay-hub.desktop by name, so the
    # taskbar/dock can look up that entry's Icon= instead of falling back to
    # a generic icon when it can't otherwise correlate the window to it.
    app.setDesktopFileName("dota-overlay-hub")
    app.setWindowIcon(QIcon(os.path.join(PROJECT_DIR, "icon.png")))
    # This is now a tray-resident app - closing/hiding every window must not
    # exit the process; only the tray menu's "Выйти" (or Ctrl+C) should.
    app.setQuitOnLastWindowClosed(False)
    window = LauncherWindow()
    window.show()
    sys.exit(app.exec())
```

- [ ] **Step 5: Manual verification**

```bash
cd /home/de1zyw/dota_overlay
python3 -c "import ast; ast.parse(open('launcher.py').read())" && echo "syntax OK"
rm -f hotkey_settings.json profile_lookup_settings.json profile_lookup_history.json
DISPLAY=:0 QT_QPA_PLATFORM=xcb timeout 30 python3 -u launcher.py
```
Expected: hub opens as before (4 sidebar tabs, 3 overlay cards). Clicking "Запустить" on any card: no new process spawned (`ps aux | grep app.py` from another terminal/tool call shows nothing new - the overlay now runs as threads/objects inside the same `launcher.py` PID), the hub window hides, and the draft overlay's hotkeys/GSI server are now live in that same process (confirm via `logs/run_*.jsonl` showing an `APP_START` event with the hub's own PID). Confirm a tray icon appears (if the desktop environment's tray is available) and clicking it brings the hub window back. Confirm clicking the hub window's own close (X) button hides it rather than exiting the process.

- [ ] **Step 6: Commit**

```bash
rm -rf logs hotkey_settings.json profile_lookup_settings.json profile_lookup_history.json
git add launcher.py
git commit -m "feat: launch the overlay in-process from the hub, hide to a tray icon"
```
