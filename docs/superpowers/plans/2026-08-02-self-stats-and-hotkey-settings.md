# Self-stats Overlay + Hotkey Settings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a hotkey-triggered self-stats overlay (10 recent matches, bigger overall numbers, works anytime) and a hub settings page to edit all three hotkey bindings, persisted to `hotkey_settings.json`.

**Architecture:** A new `hotkey_settings.py` owns load/save of the three hotkey strings (with built-in defaults), consumed by `config.py` (populates `HOTKEY_TOGGLE`/`HOTKEY_EXPAND`/`HOTKEY_SELF_STATS` at import time) and by a new Settings page in `launcher.py`. `hotkeys.py` gains a third callback and is hardened against a malformed hotkey string crashing the app. A new `self_stats_window.py` (`SelfStatsWindow`) reuses `overlay_window.py`'s private helpers (`_GradientPanel`, `_icon_label`, `_match_history_group`, `_winrate_color`) for visual consistency, wired into `app.py` via the existing `_MainThreadBridge` cross-thread pattern.

**Tech Stack:** Python stdlib (`json`) + PyQt6, same libraries already in use.

## Global Constraints

- No automated tests for this project (standing decision) — manual verification only.
- `hotkey_settings.load()`/`save()` must never raise — a missing/corrupt file falls back to defaults; a failed write just doesn't persist.
- `HotkeyListener`'s pynput binding must not crash `app.py` on a malformed hotkey string — catch and log via `event_log`, run with hotkeys unbound instead.
- Self-stats hotkey works regardless of match state (no gating on `OverlayApp.match_state`).
- Settings changes apply on next `app.py` launch, not live.
- Reuse `overlay_window.py`'s existing private helpers rather than duplicating rendering code — `_GradientPanel`, `_icon_label`, `_match_history_group`, `_winrate_color` are already plain module-level functions/classes, importable cross-module (same pattern `launcher.py` already uses for `_GradientPanel`).

---

### Task 1: `hotkey_settings.py`

**Files:**
- Create: `hotkey_settings.py`

**Interfaces:**
- Produces: `DEFAULTS: dict` (keys `toggle`, `expand`, `self_stats`), `load() -> dict` (same 3 keys, always present, falls back to `DEFAULTS` per-key and on any error), `save(hotkeys: dict) -> bool` (True on success).

- [ ] **Step 1: Write `hotkey_settings.py`**

```python
"""Persisted hotkey bindings, editable via the hub's settings page.
load() never raises - a missing/corrupt settings file just falls back to
the built-in defaults. save() never raises either - a failed write just
means the change didn't persist, reported by the caller's own UI feedback,
not a crash."""
import json
import os

SETTINGS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hotkey_settings.json")

DEFAULTS = {
    "toggle": "<ctrl>+<alt>+d",
    "expand": "<ctrl>+<alt>+e",
    "self_stats": "<ctrl>+<alt>+s",
}


def load():
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return dict(DEFAULTS)
        return {key: (data.get(key) or DEFAULTS[key]) for key in DEFAULTS}
    except (OSError, json.JSONDecodeError):
        return dict(DEFAULTS)


def save(hotkeys):
    try:
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump({key: hotkeys.get(key, DEFAULTS[key]) for key in DEFAULTS}, f, indent=2)
        return True
    except OSError:
        return False
```

- [ ] **Step 2: Manual verification**

```bash
cd /home/de1zyw/dota_overlay
rm -f hotkey_settings.json
python3 -c "
from hotkey_settings import load, save, DEFAULTS
print('defaults:', load())
assert load() == DEFAULTS
save({'toggle': '<ctrl>+<alt>+z', 'expand': '<ctrl>+<alt>+e', 'self_stats': '<ctrl>+<alt>+s'})
print('after save:', load())
"
cat hotkey_settings.json
rm -f hotkey_settings.json
```
Expected: first `load()` prints the 3 defaults; after `save()`, the second `load()` shows `toggle` changed to `<ctrl>+<alt>+z` with the other two unchanged; the file contains valid JSON with all 3 keys.

- [ ] **Step 3: Commit**

```bash
git add hotkey_settings.py
git commit -m "feat: add persisted hotkey settings (load/save, defaults)"
```

---

### Task 2: Wire `config.py` and harden `hotkeys.py`

**Files:**
- Modify: `config.py`
- Modify: `hotkeys.py`

**Interfaces:**
- Consumes: `hotkey_settings.load()` (Task 1).
- Produces: `config.HOTKEY_SELF_STATS` (new constant); `HotkeyListener(on_toggle, on_expand, on_self_stats)` (new required third param).

- [ ] **Step 1: Replace the hardcoded hotkey constants in `config.py`**

Find these two lines in `config.py`:
```python
HOTKEY_TOGGLE = "<ctrl>+<alt>+d"
HOTKEY_EXPAND = "<ctrl>+<alt>+e"
```
Replace them with:
```python
from hotkey_settings import load as _load_hotkeys

_hotkeys = _load_hotkeys()
HOTKEY_TOGGLE = _hotkeys["toggle"]
HOTKEY_EXPAND = _hotkeys["expand"]
HOTKEY_SELF_STATS = _hotkeys["self_stats"]
```
(the `from hotkey_settings import ...` line goes up near the top of the file next to the existing `from local_steam import get_local_account_id` import, not inline where the constants were — keep imports grouped at the top of the file per the file's existing style).

- [ ] **Step 2: Rewrite `hotkeys.py`**

```python
"""Global hotkeys via pynput. pynput, not `keyboard` - `keyboard` needs
root on Linux (evdev access)."""
import traceback

from pynput import keyboard

import config
import event_log


class HotkeyListener:
    def __init__(self, on_toggle, on_expand, on_self_stats):
        self._listener = None
        try:
            self._listener = keyboard.GlobalHotKeys({
                config.HOTKEY_TOGGLE: on_toggle,
                config.HOTKEY_EXPAND: on_expand,
                config.HOTKEY_SELF_STATS: on_self_stats,
            })
        except Exception as e:
            # A malformed hotkey string (e.g. hand-typo'd via the hub's
            # settings page) would otherwise crash app.py on every future
            # launch until manually fixed - log it and run with no hotkeys
            # bound instead of crashing, matching this codebase's
            # "auxiliary failure is silent, core feature keeps working"
            # convention (assets.py, opendota_client.py).
            event_log.log(
                "ERROR", where="hotkeys_init", exc_type=type(e).__name__,
                message=str(e), traceback=traceback.format_exc(),
            )

    def start(self):
        if self._listener:
            self._listener.start()

    def stop(self):
        if self._listener:
            self._listener.stop()
```

- [ ] **Step 3: Manual verification**

```bash
cd /home/de1zyw/dota_overlay
python3 -c "
import config
print(config.HOTKEY_TOGGLE, config.HOTKEY_EXPAND, config.HOTKEY_SELF_STATS)
"
rm -rf logs
python3 -c "
import event_log
event_log.init()
from hotkeys import HotkeyListener
# Deliberately malformed hotkey string to verify the crash-guard.
listener = HotkeyListener(lambda: None, lambda: None, on_self_stats=lambda: None)
listener2 = HotkeyListener.__new__(HotkeyListener)
"
python3 -c "
import config
config.HOTKEY_SELF_STATS = 'not a valid hotkey string ((('
import importlib, hotkeys
importlib.reload(hotkeys)
import event_log
event_log.init()
l = hotkeys.HotkeyListener(lambda: None, lambda: None, lambda: None)
print('listener object after bad hotkey:', l._listener)
"
cat logs/run_*.jsonl 2>/dev/null | tail -1
rm -rf logs
```
Expected: first command prints the 3 default hotkey strings. Third command prints `listener object after bad hotkey: None` (construction failed but didn't crash the process) and the log file's last line is an `ERROR` event with `where=hotkeys_init`.

- [ ] **Step 4: Commit**

```bash
git add config.py hotkeys.py
git commit -m "feat: load hotkeys from hotkey_settings, harden against bad bindings"
```

---

### Task 3: Fetch 10 recent matches instead of 5

**Files:**
- Modify: `opendota_client.py`

**Interfaces:**
- Produces: `PlayerStats.recent_matches` now holds up to 10 `(hero_id, won)` tuples instead of 5 (draft rows are unaffected — `overlay_window._match_history_group` already slices further down to its own `MATCH_HISTORY_COUNT = 5`).

- [ ] **Step 1: Change the slice in `fetch_player_stats`**

Find this line in `opendota_client.py`:
```python
    recent_matches = [
        (m.get("hero_id"), m.get("radiant_win") == (m.get("player_slot", 0) < 128))
        for m in recent[:5]
    ]
```
Change `recent[:5]` to `recent[:10]`.

Also update the `PlayerStats` dataclass's field comment:
```python
    recent_matches: list = field(default_factory=list)  # [(hero_id, won: bool), ...], newest first, max 5
```
to say `max 10` instead of `max 5`.

- [ ] **Step 2: Manual verification**

```bash
cd /home/de1zyw/dota_overlay
python3 -c "
from opendota_client import fetch_player_stats
stats = fetch_player_stats(111620041)
print(len(stats.recent_matches), 'matches fetched')
"
```
Expected: prints a number up to 10 (exact count depends on how many real matches that account has - this is a real public account used elsewhere in this project's manual tests, so it should return 10 unless OpenDota has fewer on file).

- [ ] **Step 3: Commit**

```bash
git add opendota_client.py
git commit -m "feat: fetch 10 recent matches instead of 5 for the self-stats view"
```

---

### Task 4: `self_stats_window.py`

**Files:**
- Create: `self_stats_window.py`

**Interfaces:**
- Consumes: `overlay_window._GradientPanel`, `overlay_window._icon_label`, `overlay_window._match_history_group`, `overlay_window._winrate_color` (all existing), `assets.get_rank_icon_path` (existing), `config.WINDOW_OPACITY`/`WINDOW_MARGIN_PX` (existing), `opendota_client.PlayerStats` (Task 3's shape, existing type).
- Produces: `SelfStatsWindow` with `.render_stats(stats_or_none)`, `.show_stats()`, `.hide_stats()`, `.toggle()`.

- [ ] **Step 1: Write `self_stats_window.py`**

```python
"""Dedicated on-demand window showing the local user's own OpenDota stats
in more detail than a draft row - bigger overall numbers, 10 recent
matches instead of 5 (two rows of 5). Toggled by a hotkey, independent of
match state. Reuses overlay_window.py's private helpers for the same
dark-gradient visual style rather than duplicating that rendering code."""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

import config
from assets import get_rank_icon_path
from overlay_window import _GradientPanel, _icon_label, _match_history_group, _winrate_color

RANK_ICON_SIZE = 48


class SelfStatsWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowOpacity(config.WINDOW_OPACITY)

        self._panel = _GradientPanel()
        self._layout = QVBoxLayout(self._panel)
        self._layout.setContentsMargins(20, 18, 20, 18)
        self._layout.setSpacing(8)

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

    def render_stats(self, stats):
        self._clear_layout()

        if stats is None:
            msg = QLabel("Steam-аккаунт не определён — стата недоступна")
            msg.setStyleSheet("color: #aaaaaa; font-family: sans-serif; font-size: 13px;")
            self._layout.addWidget(msg)
            self._panel.adjustSize()
            self.adjustSize()
            return

        header = QHBoxLayout()
        header.addWidget(_icon_label(get_rank_icon_path(stats.rank_tier), RANK_ICON_SIZE))
        nickname = QLabel(stats.nickname)
        nickname.setStyleSheet(
            "color: white; font-weight: bold; font-family: sans-serif; font-size: 20px;"
        )
        header.addWidget(nickname)
        header.addStretch()
        self._layout.addLayout(header)

        winrate_str = f"{stats.winrate:.0f}%" if stats.winrate is not None else "н/д"
        overall = QLabel(f"WR {winrate_str}  •  {stats.total_games} игр")
        overall.setStyleSheet(
            f"color: {_winrate_color(stats.winrate)}; font-family: sans-serif; "
            "font-size: 18px; font-weight: 600;"
        )
        self._layout.addWidget(overall)

        history_label = QLabel("ПОСЛЕДНИЕ МАТЧИ")
        history_label.setStyleSheet(
            "color: #888899; font-family: sans-serif; font-size: 11px; "
            "font-weight: bold; letter-spacing: 1px;"
        )
        self._layout.addWidget(history_label)

        self._layout.addWidget(_match_history_group(stats.recent_matches[0:5]))
        self._layout.addWidget(_match_history_group(stats.recent_matches[5:10]))

        self._panel.adjustSize()
        self.adjustSize()

    def show_stats(self):
        self.show()

    def hide_stats(self):
        self.hide()

    def toggle(self):
        if self.isVisible():
            self.hide_stats()
        else:
            self.show_stats()
```

- [ ] **Step 2: Manual verification**

```bash
cd /home/de1zyw/dota_overlay
DISPLAY=:0 QT_QPA_PLATFORM=xcb python3 -c "
import sys
from PyQt6.QtWidgets import QApplication
from self_stats_window import SelfStatsWindow
from opendota_client import fetch_player_stats

app = QApplication(sys.argv)
w = SelfStatsWindow()
w.render_stats(fetch_player_stats(111620041))
w.show_stats()
sys.exit(app.exec())
" &
sleep 3
wmctrl -l 2>/dev/null | grep -i python
kill %1 2>/dev/null
```
Expected: a window appears (visible via `wmctrl`) with the same dark-gradient background as the main overlay, a rank icon + nickname header, a bigger `WR .. • .. игр` line, and two rows of match-history icons (up to 5 each). Also verify the `stats=None` path: replace `fetch_player_stats(111620041)` with `None` in the same snippet and confirm the "Steam-аккаунт не определён" message shows instead of a crash.

- [ ] **Step 3: Commit**

```bash
git add self_stats_window.py
git commit -m "feat: add SelfStatsWindow for the hotkey-triggered self-stats view"
```

---

### Task 5: Wire the self-stats hotkey into `app.py`

**Files:**
- Modify: `app.py`

**Interfaces:**
- Consumes: `SelfStatsWindow` (Task 4), `HotkeyListener(on_toggle, on_expand, on_self_stats)` (Task 2), `config.HOTKEY_SELF_STATS` (Task 2), `config.MY_ACCOUNT_ID` (existing), `opendota_client.fetch_player_stats` (existing, Task 3's richer output).

- [ ] **Step 1: Import `SelfStatsWindow`**

Add to `app.py`'s imports, alongside `from overlay_window import OverlayWindow`:
```python
from self_stats_window import SelfStatsWindow
```

- [ ] **Step 2: Add a bridge signal + slot for the self-stats toggle**

In `_MainThreadBridge`, add a new signal next to the existing three:
```python
    self_stats_ready = pyqtSignal(object)
```
In `_MainThreadBridge.__init__`, accept and store the self-stats window, and connect the new signal:
```python
    def __init__(self, window, hide_timer, self_stats_window):
        super().__init__()
        self._window = window
        self._hide_timer = hide_timer
        self._self_stats_window = self_stats_window
        self.new_match_ready.connect(self._on_new_match_ready)
        self.toggle_visibility_requested.connect(self._on_toggle_visibility)
        self.expand_requested.connect(self._on_expand)
        self.self_stats_ready.connect(self._on_self_stats_ready)
```
Add the new slot method (anywhere among the other `_on_*` methods in this class):
```python
    def _on_self_stats_ready(self, stats):
        # Always re-fetched on every hotkey press (see OverlayApp.
        # on_self_stats_hotkey below), including the press that's about to
        # close it - a same-account repeat fetch within 30s is served from
        # opendota_client's own cache, so this is cheap, not wasteful.
        if self._self_stats_window.isVisible():
            self._self_stats_window.hide_stats()
        else:
            self._self_stats_window.render_stats(stats)
            self._self_stats_window.show_stats()
```

- [ ] **Step 3: Construct `SelfStatsWindow` and pass it to the bridge**

In `OverlayApp.__init__`, add right after `self.window = OverlayWindow()`:
```python
        self.self_stats_window = SelfStatsWindow()
```
Change the bridge construction line from:
```python
        self.bridge = _MainThreadBridge(self.window, self.hide_timer)
```
to:
```python
        self.bridge = _MainThreadBridge(self.window, self.hide_timer, self.self_stats_window)
```

- [ ] **Step 4: Add the hotkey callback and pass it to `HotkeyListener`**

Add a new method to `OverlayApp` (near `on_new_match`):
```python
    def on_self_stats_hotkey(self):
        # Runs on pynput's own listener thread (see this module's
        # docstring) - blocking here on the network fetch is fine, it
        # doesn't freeze the UI. Only the actual show/hide + render must
        # happen on the main thread, via the bridge signal below.
        stats = fetch_player_stats(config.MY_ACCOUNT_ID) if config.MY_ACCOUNT_ID else None
        self.bridge.self_stats_ready.emit(stats)
```
Change the `HotkeyListener` construction from:
```python
        self.hotkeys = HotkeyListener(
            on_toggle=self.bridge.toggle_visibility_requested.emit,
            on_expand=self.bridge.expand_requested.emit,
        )
```
to:
```python
        self.hotkeys = HotkeyListener(
            on_toggle=self.bridge.toggle_visibility_requested.emit,
            on_expand=self.bridge.expand_requested.emit,
            on_self_stats=self.on_self_stats_hotkey,
        )
```

- [ ] **Step 5: Manual verification**

```bash
cd /home/de1zyw/dota_overlay
python3 -c "import ast; ast.parse(open('app.py').read())" && echo "syntax OK"
cp fixtures/server_log_sample.txt /tmp/my_test_log.txt
DISPLAY=:0 QT_QPA_PLATFORM=xcb timeout 15 python3 run_demo.py
```
Expected: syntax check passes; the demo runs without crashing for the full 15s (same baseline behavior as every prior manual run this session - this step is really just confirming the new wiring didn't break app startup, since pynput hotkeys don't fire in this sandboxed test environment anyway per the project's documented Wayland/X11 hotkey limitation - the deeper verification is Task 4's already-confirmed standalone `SelfStatsWindow` rendering, plus Task 2's confirmation that `HotkeyListener` now accepts and binds `on_self_stats` without raising).

- [ ] **Step 6: Commit**

```bash
git add app.py
git commit -m "feat: wire the self-stats hotkey into app.py"
```

---

### Task 6: Hotkey settings page in the hub

**Files:**
- Modify: `launcher.py`

**Interfaces:**
- Consumes: `hotkey_settings.load()`/`save()` (Task 1).

- [ ] **Step 1: Import `hotkey_settings` and add `QLineEdit`/`QStackedWidget` (already imported) to `launcher.py`'s imports**

Add near the top of `launcher.py`:
```python
import hotkey_settings
```
Add `QLineEdit` to the existing `from PyQt6.QtWidgets import (...)` block (alphabetical among the existing names).

- [ ] **Step 2: Add a `_SettingsPage` class**

Add this class right after `_LogsPage` in `launcher.py`:
```python
class _SettingsPage(QWidget):
    _FIELD_LABELS = [
        ("toggle", "Показать/скрыть"),
        ("expand", "Свернуть/развернуть"),
        ("self_stats", "Моя стата"),
    ]

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        title = QLabel("Настройки хоткеев")
        title.setStyleSheet("color: white; font-weight: bold; font-family: sans-serif; font-size: 14px;")
        layout.addWidget(title)

        current = hotkey_settings.load()
        self._fields = {}
        for key, label_text in self._FIELD_LABELS:
            row = QHBoxLayout()
            label = QLabel(label_text)
            label.setFixedWidth(160)
            label.setStyleSheet("color: #cccccc; font-family: sans-serif; font-size: 12px;")
            row.addWidget(label)

            field = QLineEdit(current[key])
            field.setStyleSheet(
                "QLineEdit { background-color: rgba(255,255,255,10); color: white; "
                "border: 1px solid rgba(255,255,255,30); border-radius: 4px; padding: 4px 8px; "
                "font-family: monospace; font-size: 12px; }"
            )
            row.addWidget(field)
            self._fields[key] = field
            layout.addLayout(row)

        self._status_label = QLabel("")
        self._status_label.setStyleSheet("color: #aaaaaa; font-family: sans-serif; font-size: 11px;")
        layout.addWidget(self._status_label)

        save_btn = QPushButton("Сохранить")
        save_btn.setStyleSheet(PRIMARY_BUTTON_STYLE)
        save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        save_btn.clicked.connect(self._on_save)
        layout.addWidget(save_btn)

        layout.addStretch()

    def _on_save(self):
        values = {key: field.text().strip() for key, field in self._fields.items()}
        ok = hotkey_settings.save(values)
        if ok:
            self._status_label.setText("Сохранено — изменения применятся при следующем запуске оверлея")
        else:
            self._status_label.setText("Не удалось сохранить настройки")
```

- [ ] **Step 3: Add the third sidebar entry and page in `LauncherWindow`**

In `LauncherWindow.__init__`, find:
```python
        self._stack = QStackedWidget()
        overlays_btn = QPushButton("ОВЕРЛЕИ")
        logs_btn = QPushButton("ЛОГИ")
        for btn in (overlays_btn, logs_btn):
```
Change to:
```python
        self._stack = QStackedWidget()
        overlays_btn = QPushButton("ОВЕРЛЕИ")
        logs_btn = QPushButton("ЛОГИ")
        settings_btn = QPushButton("НАСТРОЙКИ")
        for btn in (overlays_btn, logs_btn, settings_btn):
```
Find:
```python
        overlays_btn.setChecked(True)
        overlays_btn.clicked.connect(lambda: self._switch_page(0, overlays_btn, logs_btn))
        logs_btn.clicked.connect(lambda: self._switch_page(1, overlays_btn, logs_btn))
        sidebar_layout.addWidget(overlays_btn)
        sidebar_layout.addWidget(logs_btn)
        sidebar_layout.addStretch()
```
Change to:
```python
        overlays_btn.setChecked(True)
        overlays_btn.clicked.connect(lambda: self._switch_page(0, [overlays_btn, logs_btn, settings_btn]))
        logs_btn.clicked.connect(lambda: self._switch_page(1, [overlays_btn, logs_btn, settings_btn]))
        settings_btn.clicked.connect(lambda: self._switch_page(2, [overlays_btn, logs_btn, settings_btn]))
        sidebar_layout.addWidget(overlays_btn)
        sidebar_layout.addWidget(logs_btn)
        sidebar_layout.addWidget(settings_btn)
        sidebar_layout.addStretch()
```
Find:
```python
        self._overlays_page = _OverlaysPage()
        self._logs_page = _LogsPage()
        self._stack.addWidget(self._overlays_page)
        self._stack.addWidget(self._logs_page)
        content_layout.addWidget(self._stack)
        panel_layout.addWidget(content)

    def _switch_page(self, index, overlays_btn, logs_btn):
        self._stack.setCurrentIndex(index)
        overlays_btn.setChecked(index == 0)
        logs_btn.setChecked(index == 1)
        if index == 1:
            self._logs_page.refresh()
```
Change to:
```python
        self._overlays_page = _OverlaysPage()
        self._logs_page = _LogsPage()
        self._settings_page = _SettingsPage()
        self._stack.addWidget(self._overlays_page)
        self._stack.addWidget(self._logs_page)
        self._stack.addWidget(self._settings_page)
        content_layout.addWidget(self._stack)
        panel_layout.addWidget(content)

    def _switch_page(self, index, nav_buttons):
        self._stack.setCurrentIndex(index)
        for i, btn in enumerate(nav_buttons):
            btn.setChecked(i == index)
        if index == 1:
            self._logs_page.refresh()
```
(the `_switch_page` signature changes from `(index, overlays_btn, logs_btn)` to `(index, nav_buttons)` — a list — since there are now 3 buttons to keep in sync instead of 2; all three call sites above already pass the 3-button list form.)

- [ ] **Step 4: Manual verification**

```bash
cd /home/de1zyw/dota_overlay
python3 -c "import ast; ast.parse(open('launcher.py').read())" && echo "syntax OK"
rm -f hotkey_settings.json
DISPLAY=:0 QT_QPA_PLATFORM=xcb timeout 30 python3 -u launcher.py
```
Expected: hub opens with 3 sidebar entries (ОВЕРЛЕИ/ЛОГИ/НАСТРОЙКИ). Clicking НАСТРОЙКИ shows 3 labeled fields pre-filled with the defaults (`<ctrl>+<alt>+d`, `<ctrl>+<alt>+e`, `<ctrl>+<alt>+s`) and a gradient-styled "Сохранить" button. Change one field's text, click Сохранить, confirm the status line says it saved, and confirm `hotkey_settings.json` now exists on disk with the edited value:
```bash
cat hotkey_settings.json
rm -f hotkey_settings.json
```

- [ ] **Step 5: Commit**

```bash
git add launcher.py
git commit -m "feat: add hotkey settings page to the hub"
```
