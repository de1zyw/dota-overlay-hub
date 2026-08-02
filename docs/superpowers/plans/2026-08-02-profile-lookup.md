# OCR Profile Lookup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Two new hotkeys — calibrate a screen region once, then OCR-read a profile nickname from it on demand, search OpenDota, disambiguate if needed, show stats, and log history — per the approved design spec.

**Architecture:** Two new leaf persistence modules (`profile_lookup_settings.py`, `profile_lookup_history.py`, same never-raises pattern as `hotkey_settings.py`), a pure OCR pipeline (`ocr_capture.py`, no Qt), two new small Qt windows (`region_calibrator.py`, `candidate_picker_window.py`), a rename of `SelfStatsWindow`→`PlayerStatsWindow` (already-generic rendering, now explicitly shared by two features), all wired into `app.py` via the existing `_MainThreadBridge` cross-thread pattern, plus hub UI updates (2 new hotkey settings fields, a real overlay card replacing the coming-soon placeholder, a new История page).

**Tech Stack:** `mss` (screen capture) + `pytesseract` (OCR, wraps the system `tesseract` binary) — both new. Everything else is existing stdlib/PyQt6/requests.

## Global Constraints

- No automated tests for this project (standing decision) — manual verification only.
- Every new persistence module (`profile_lookup_settings.py`, `profile_lookup_history.py`) never raises — missing/corrupt files fall back to empty/None, failed writes just don't persist.
- The `tesseract` binary is a system package (installed via `pacman`/`dnf`, not pip) — the launcher cannot install it itself; it's a hard-blocker check, not an auto-fix.
- Zero OCR/search matches must show a clear "not found" message, never a guess. Multiple matches must show a picker, never auto-pick the first.
- Reuse existing patterns: `overlay_window._GradientPanel` for visual consistency, `_MainThreadBridge` for all cross-thread window operations, `event_log.log(...)` for diagnostic events on every new hotkey/action.

---

### Task 1: Persistence modules

**Files:**
- Create: `profile_lookup_settings.py`
- Create: `profile_lookup_history.py`

**Interfaces:**
- Produces: `profile_lookup_settings.load() -> dict|None` (keys `x, y, width, height`, or `None` if never calibrated), `profile_lookup_settings.save(region: dict) -> bool`.
- Produces: `profile_lookup_history.load_all() -> list[dict]` (each `{account_id, nickname, timestamp}`, newest first), `profile_lookup_history.append(account_id, nickname) -> bool`.

- [ ] **Step 1: Write `profile_lookup_settings.py`**

```python
"""Persisted screen region for profile-lookup OCR, calibrated once by the
user via region_calibrator.py. load() never raises - returns None if no
region has been calibrated yet (the feature simply can't do anything
useful until then, same as any other unmet prerequisite in this app).
save() never raises either - a failed write just means the calibration
didn't persist."""
import json
import os

SETTINGS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "profile_lookup_settings.json")


def load():
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return None
        if any(data.get(key) is None for key in ("x", "y", "width", "height")):
            return None
        return {key: data[key] for key in ("x", "y", "width", "height")}
    except (OSError, json.JSONDecodeError):
        return None


def save(region):
    try:
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(region, f, indent=2)
        return True
    except OSError:
        return False
```

- [ ] **Step 2: Write `profile_lookup_history.py`**

```python
"""Persisted history of profile lookups (nickname + account_id + when),
so the hub's ИСТОРИЯ page can show past lookups without redoing OCR.
Never raises - a corrupt/missing history file is treated as empty."""
import json
import os
from datetime import datetime, timezone

HISTORY_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "profile_lookup_history.json")
MAX_ENTRIES = 100


def load_all():
    try:
        with open(HISTORY_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            return []
        return data
    except (OSError, json.JSONDecodeError):
        return []


def append(account_id, nickname):
    entries = load_all()
    entries.insert(0, {
        "account_id": account_id,
        "nickname": nickname,
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    })
    entries = entries[:MAX_ENTRIES]
    try:
        with open(HISTORY_PATH, "w", encoding="utf-8") as f:
            json.dump(entries, f, indent=2)
        return True
    except OSError:
        return False
```

- [ ] **Step 3: Manual verification**

```bash
cd /home/de1zyw/dota_overlay
rm -f profile_lookup_settings.json profile_lookup_history.json
python3 -c "
import profile_lookup_settings as s
print('no region yet:', s.load())
s.save({'x': 100, 'y': 200, 'width': 300, 'height': 40})
print('after save:', s.load())
"
python3 -c "
import profile_lookup_history as h
print('empty history:', h.load_all())
h.append(111620041, 'Miracle-')
h.append(222222222, 'SomeoneElse')
for entry in h.load_all():
    print(entry)
"
rm -f profile_lookup_settings.json profile_lookup_history.json
```
Expected: first script prints `None` then the round-tripped region dict; second script prints `[]` then two entries with the most recently appended one first.

- [ ] **Step 4: Commit**

```bash
git add profile_lookup_settings.py profile_lookup_history.py
git commit -m "feat: add persistence for profile-lookup region + history"
```

---

### Task 2: OpenDota nickname search

**Files:**
- Modify: `opendota_client.py`

**Interfaces:**
- Produces: `search_players(name: str) -> list[dict]`, each dict `{account_id, nickname, avatar_url}`, max 5, empty list on any failure or zero matches.

- [ ] **Step 1: Add `search_players` to `opendota_client.py`**

Add this function anywhere after `_cached_get` is defined (e.g. right before the `PlayerStats` dataclass):

```python
def search_players(name):
    try:
        results = _cached_get("/search", params={"q": name}, ttl=20) or []
    except OpenDotaError:
        return []
    return [
        {
            "account_id": r.get("account_id"),
            "nickname": r.get("personaname") or f"[{r.get('account_id')}]",
            "avatar_url": r.get("avatarfull"),
        }
        for r in results
        if r.get("account_id") is not None
    ][:5]
```

- [ ] **Step 2: Manual verification**

```bash
cd /home/de1zyw/dota_overlay
python3 -c "
from opendota_client import search_players
results = search_players('Miracle')
print(len(results), 'candidates')
for r in results:
    print(r['account_id'], r['nickname'])
"
```
Expected: a small list of candidate dicts (0-5), each with a real `account_id` and `nickname` - no exception even if OpenDota is briefly slow (the existing retry/throttle logic in `_get`/`_cached_get` already handles that).

- [ ] **Step 3: Commit**

```bash
git add opendota_client.py
git commit -m "feat: add OpenDota nickname search for profile lookup"
```

---

### Task 3: Two new hotkeys end-to-end (settings, config, listener, hub UI)

**Files:**
- Modify: `hotkey_settings.py`
- Modify: `config.py`
- Modify: `hotkeys.py`
- Modify: `launcher.py`

**Interfaces:**
- Produces: `hotkey_settings.DEFAULTS` gains `calibrate`/`profile_lookup` keys; `config.HOTKEY_CALIBRATE`/`config.HOTKEY_PROFILE_LOOKUP`; `HotkeyListener(on_toggle, on_expand, on_self_stats, on_calibrate, on_profile_lookup)` (2 new required params).

- [ ] **Step 1: Add the 2 new keys to `hotkey_settings.py`'s `DEFAULTS`**

Change:
```python
DEFAULTS = {
    "toggle": "<ctrl>+<alt>+d",
    "expand": "<ctrl>+<alt>+e",
    "self_stats": "<ctrl>+<alt>+s",
}
```
to:
```python
DEFAULTS = {
    "toggle": "<ctrl>+<alt>+d",
    "expand": "<ctrl>+<alt>+e",
    "self_stats": "<ctrl>+<alt>+s",
    "calibrate": "<ctrl>+<alt>+r",
    "profile_lookup": "<ctrl>+<alt>+p",
}
```

- [ ] **Step 2: Add the 2 new constants to `config.py`**

Change:
```python
_hotkeys = _load_hotkeys()
HOTKEY_TOGGLE = _hotkeys["toggle"]
HOTKEY_EXPAND = _hotkeys["expand"]
HOTKEY_SELF_STATS = _hotkeys["self_stats"]
```
to:
```python
_hotkeys = _load_hotkeys()
HOTKEY_TOGGLE = _hotkeys["toggle"]
HOTKEY_EXPAND = _hotkeys["expand"]
HOTKEY_SELF_STATS = _hotkeys["self_stats"]
HOTKEY_CALIBRATE = _hotkeys["calibrate"]
HOTKEY_PROFILE_LOOKUP = _hotkeys["profile_lookup"]
```

- [ ] **Step 3: Update `HotkeyListener` in `hotkeys.py`**

Change:
```python
class HotkeyListener:
    def __init__(self, on_toggle, on_expand, on_self_stats):
        self._listener = None
        try:
            self._listener = keyboard.GlobalHotKeys({
                config.HOTKEY_TOGGLE: on_toggle,
                config.HOTKEY_EXPAND: on_expand,
                config.HOTKEY_SELF_STATS: on_self_stats,
            })
```
to:
```python
class HotkeyListener:
    def __init__(self, on_toggle, on_expand, on_self_stats, on_calibrate, on_profile_lookup):
        self._listener = None
        try:
            self._listener = keyboard.GlobalHotKeys({
                config.HOTKEY_TOGGLE: on_toggle,
                config.HOTKEY_EXPAND: on_expand,
                config.HOTKEY_SELF_STATS: on_self_stats,
                config.HOTKEY_CALIBRATE: on_calibrate,
                config.HOTKEY_PROFILE_LOOKUP: on_profile_lookup,
            })
```

- [ ] **Step 4: Add the 2 new fields to `launcher.py`'s `_SettingsPage`**

Change:
```python
    _FIELD_LABELS = [
        ("toggle", "Показать/скрыть"),
        ("expand", "Свернуть/развернуть"),
        ("self_stats", "Моя стата"),
    ]
```
to:
```python
    _FIELD_LABELS = [
        ("toggle", "Показать/скрыть"),
        ("expand", "Свернуть/развернуть"),
        ("self_stats", "Моя стата"),
        ("calibrate", "Калибровка профиля"),
        ("profile_lookup", "Профиль по клику"),
    ]
```

- [ ] **Step 5: Manual verification**

```bash
cd /home/de1zyw/dota_overlay
python3 -c "
import config
print(config.HOTKEY_TOGGLE, config.HOTKEY_EXPAND, config.HOTKEY_SELF_STATS, config.HOTKEY_CALIBRATE, config.HOTKEY_PROFILE_LOOKUP)
"
python3 -c "
from hotkeys import HotkeyListener
l = HotkeyListener(lambda: None, lambda: None, lambda: None, lambda: None, lambda: None)
print('listener:', l._listener)
"
python3 -c "import ast; ast.parse(open('launcher.py').read())" && echo "launcher.py syntax OK"
```
Expected: 5 hotkey strings print (including the 2 new defaults); `HotkeyListener` constructs successfully with 5 callbacks (`listener` is not `None`); `launcher.py` still parses.

- [ ] **Step 6: Commit**

```bash
git add hotkey_settings.py config.py hotkeys.py launcher.py
git commit -m "feat: add calibrate/profile_lookup hotkey slots end-to-end"
```

---

### Task 4: Launcher checklist for the profile-lookup feature

**Files:**
- Modify: `launcher_checks.py`

**Interfaces:**
- Consumes: `profile_lookup_settings.load()` (Task 1), `config.HOTKEY_CALIBRATE` (Task 3).
- Produces: `PROFILE_LOOKUP_CHECKS: list[tuple[str, callable]]`.

- [ ] **Step 1: Add the tesseract + calibration checks**

Add `import shutil` to the top of `launcher_checks.py` alongside the existing `import importlib.util` / `import os`. Then add, after the existing `check_steam_account_self_stats` function:

```python
def check_tesseract():
    if shutil.which("tesseract"):
        return STATUS_OK, "tesseract установлен"
    return STATUS_ERROR, "tesseract не найден — установи: sudo pacman -S tesseract tesseract-data-rus (Arch/CachyOS)"


def check_region_calibrated():
    import profile_lookup_settings
    if profile_lookup_settings.load() is not None:
        return STATUS_OK, "Область экрана откалибрована"
    return STATUS_WARN, f"Область экрана не откалибрована — открой профиль в Доте и нажми {config.HOTKEY_CALIBRATE}"
```

Then add, after `SELF_STATS_CHECKS`:

```python
PROFILE_LOOKUP_CHECKS = [
    ("Python-зависимости", check_dependencies),
    ("tesseract", check_tesseract),
    ("Область экрана", check_region_calibrated),
]
```

(the `import profile_lookup_settings` is placed inside `check_region_calibrated` rather than at module top, since `launcher_checks.py` is meant to be importable standalone even before every leaf module exists — matches no other existing check needing a project-local import at module scope; a local import here keeps the module's own top-level import list minimal.)

- [ ] **Step 2: Manual verification**

```bash
cd /home/de1zyw/dota_overlay
rm -f profile_lookup_settings.json
python3 -c "
from launcher_checks import PROFILE_LOOKUP_CHECKS
for label, fn in PROFILE_LOOKUP_CHECKS:
    print(label, fn())
"
```
Expected: 3 lines print; `tesseract` shows `ok` if the binary happens to be installed on this dev machine or the exact error message with the install command if not; `Область экрана` shows the warning message (since no calibration file exists yet).

- [ ] **Step 3: Commit**

```bash
git add launcher_checks.py
git commit -m "feat: add tesseract + calibration checks for profile lookup"
```

---

### Task 5: OCR pipeline

**Files:**
- Create: `ocr_capture.py`
- Modify: `requirements.txt`

**Interfaces:**
- Produces: `capture_region(region: dict) -> PIL.Image.Image | None`, `read_nickname(image) -> str` (empty string on any failure).

- [ ] **Step 1: Add `mss` and `pytesseract` to `requirements.txt`**

Add two lines to `requirements.txt`:
```
mss==9.0.2
pytesseract==0.3.13
```

- [ ] **Step 2: Install the new dependencies**

```bash
pip install -r requirements.txt --break-system-packages
```

- [ ] **Step 3: Write `ocr_capture.py`**

```python
"""Pure OCR pipeline for profile lookup: screen-capture a calibrated
region and read the nickname text out of it. No Qt dependency - safe to
call from a background/pynput thread. Never raises - a failed capture or
unreadable image just means the lookup can't proceed this time, not a
crash (mirrors every other "auxiliary failure is silent" module in this
project: assets.py, opendota_client.py)."""
import mss
import pytesseract
from PIL import Image


def capture_region(region):
    try:
        with mss.mss() as sct:
            monitor = {
                "left": region["x"], "top": region["y"],
                "width": region["width"], "height": region["height"],
            }
            shot = sct.grab(monitor)
            return Image.frombytes("RGB", shot.size, shot.rgb)
    except Exception:
        return None


def read_nickname(image):
    if image is None:
        return ""
    try:
        raw = pytesseract.image_to_string(image, lang="rus+eng")
        lines = [line.strip() for line in raw.splitlines() if line.strip()]
        return lines[0] if lines else ""
    except Exception:
        return ""
```

- [ ] **Step 4: Manual verification**

```bash
cd /home/de1zyw/dota_overlay
python3 -c "
from ocr_capture import capture_region, read_nickname
img = capture_region({'x': 0, 'y': 0, 'width': 400, 'height': 100})
print('capture result:', img)
print('nickname read:', repr(read_nickname(img)))
print('None-image path:', repr(read_nickname(None)))
"
```
Expected: `capture result` shows a real `PIL.Image.Image` object (capturing whatever is actually on this machine's screen at that corner - content doesn't matter for this check, only that capture succeeded without raising); `nickname read` prints whatever text OCR found there (may well be empty/garbage since it's not pointed at anything meaningful - that's fine, the point is no exception); `None-image path` prints `''`.

- [ ] **Step 5: Commit**

```bash
git add ocr_capture.py requirements.txt
git commit -m "feat: add pure OCR capture+read pipeline for profile lookup"
```

---

### Task 6: Region calibrator window

**Files:**
- Create: `region_calibrator.py`

**Interfaces:**
- Consumes: `profile_lookup_settings.save(region)` (Task 1).
- Produces: `RegionCalibrator(on_done)` — a `QWidget`; `on_done` is called with a region dict on a successful drag-select, or `None` if cancelled (Escape) or the drag was too small to count.

- [ ] **Step 1: Write `region_calibrator.py`**

```python
"""Fullscreen transparent overlay for one-time drag-to-select calibration
of the profile-lookup OCR region. Shown via a hotkey while a real Dota
profile screen is visible behind it - this only works because Linux Dota
typically runs fullscreen-*windowed*, not exclusive fullscreen, so this
overlay can render on top while the game keeps rendering underneath."""
from PyQt6.QtCore import QRect, Qt
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import QWidget

import profile_lookup_settings


class RegionCalibrator(QWidget):
    def __init__(self, on_done):
        super().__init__()
        self._on_done = on_done
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self._start = None
        self._current = None
        self.showFullScreen()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 60))
        if self._start and self._current:
            rect = QRect(self._start, self._current).normalized()
            painter.setPen(QPen(QColor("#7DD3FC"), 2))
            painter.fillRect(rect, QColor(255, 255, 255, 30))
            painter.drawRect(rect)

    def mousePressEvent(self, event):
        self._start = event.pos()
        self._current = event.pos()
        self.update()

    def mouseMoveEvent(self, event):
        if self._start:
            self._current = event.pos()
            self.update()

    def mouseReleaseEvent(self, event):
        if not self._start:
            return
        rect = QRect(self._start, event.pos()).normalized()
        self.close()
        if rect.width() > 4 and rect.height() > 4:
            top_left = self.mapToGlobal(rect.topLeft())
            region = {
                "x": top_left.x(), "y": top_left.y(),
                "width": rect.width(), "height": rect.height(),
            }
            profile_lookup_settings.save(region)
            self._on_done(region)
        else:
            self._on_done(None)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            self._on_done(None)
```

- [ ] **Step 2: Manual verification**

```bash
cd /home/de1zyw/dota_overlay
rm -f profile_lookup_settings.json
python3 -c "import ast; ast.parse(open('region_calibrator.py').read())" && echo "syntax OK"
DISPLAY=:0 QT_QPA_PLATFORM=xcb timeout 15 python3 -c "
import sys
from PyQt6.QtWidgets import QApplication
from region_calibrator import RegionCalibrator

app = QApplication(sys.argv)
def done(region):
    print('CALIBRATION RESULT:', region)
    app.quit()
w = RegionCalibrator(on_done=done)
sys.exit(app.exec())
"
```
Expected: a dark semi-transparent fullscreen overlay appears; dragging the mouse draws a live-updating blue-outlined selection rectangle; releasing the mouse prints `CALIBRATION RESULT: {...}` with the dragged rectangle's screen coordinates and closes the app. Pressing Escape instead prints `CALIBRATION RESULT: None`. Confirm `profile_lookup_settings.json` was written after a successful drag:
```bash
cat profile_lookup_settings.json
rm -f profile_lookup_settings.json
```

- [ ] **Step 3: Commit**

```bash
git add region_calibrator.py
git commit -m "feat: add drag-to-select region calibrator window"
```

---

### Task 7: Candidate picker window

**Files:**
- Create: `candidate_picker_window.py`

**Interfaces:**
- Consumes: `overlay_window._GradientPanel` (existing).
- Produces: `CandidatePickerWindow(on_selected)` — `.show_candidates(candidates: list[dict])` (each dict has `account_id`, `nickname`, matching `opendota_client.search_players`'s return shape); `on_selected(candidate: dict)` fires when a row is clicked.

- [ ] **Step 1: Write `candidate_picker_window.py`**

```python
"""Small window listing OpenDota nickname-search candidates for the user
to pick the right account from, since nicknames aren't unique. Reuses the
overlay's own dark-gradient styling for visual consistency."""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

from overlay_window import _GradientPanel


class CandidatePickerWindow(QWidget):
    def __init__(self, on_selected):
        super().__init__()
        self._on_selected = on_selected
        self.setWindowTitle("Выбери профиль")
        self.resize(360, 300)

        self._panel = _GradientPanel()
        self._layout = QVBoxLayout(self._panel)
        self._layout.setContentsMargins(16, 14, 16, 14)
        self._layout.setSpacing(6)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self._panel)

        title = QLabel("Несколько совпадений — выбери нужного")
        title.setWordWrap(True)
        title.setStyleSheet(
            "color: white; font-weight: bold; font-family: sans-serif; font-size: 13px;"
        )
        self._layout.addWidget(title)

    def show_candidates(self, candidates):
        while self._layout.count() > 1:
            item = self._layout.takeAt(1)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        for candidate in candidates:
            btn = QPushButton(candidate["nickname"])
            btn.setStyleSheet(
                "QPushButton { text-align: left; color: white; background-color: rgba(255,255,255,12); "
                "border: none; border-radius: 6px; padding: 8px; font-family: sans-serif; font-size: 13px; }"
                "QPushButton:hover { background-color: rgba(255,255,255,22); }"
            )
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda checked=False, c=candidate: self._select(c))
            self._layout.addWidget(btn)

        self.show()

    def _select(self, candidate):
        self.close()
        self._on_selected(candidate)
```

- [ ] **Step 2: Manual verification**

```bash
cd /home/de1zyw/dota_overlay
python3 -c "import ast; ast.parse(open('candidate_picker_window.py').read())" && echo "syntax OK"
DISPLAY=:0 QT_QPA_PLATFORM=xcb timeout 15 python3 -c "
import sys
from PyQt6.QtWidgets import QApplication
from candidate_picker_window import CandidatePickerWindow

app = QApplication(sys.argv)
def selected(c):
    print('SELECTED:', c)
    app.quit()
w = CandidatePickerWindow(on_selected=selected)
w.show_candidates([
    {'account_id': 111620041, 'nickname': 'Miracle-', 'avatar_url': None},
    {'account_id': 222222222, 'nickname': 'SomeoneElse', 'avatar_url': None},
])
sys.exit(app.exec())
"
```
Expected: a window titled "Выбери профиль" appears listing the 2 candidate names as clickable rows over the dark-gradient background; clicking one prints `SELECTED: {...}` with that candidate's dict and closes the window/app.

- [ ] **Step 3: Commit**

```bash
git add candidate_picker_window.py
git commit -m "feat: add candidate picker window for profile-lookup disambiguation"
```

---

### Task 8: Rename `SelfStatsWindow` to `PlayerStatsWindow`

**Files:**
- Modify: `self_stats_window.py` → rename file to `player_stats_window.py`

**Interfaces:**
- Produces: `PlayerStatsWindow` (was `SelfStatsWindow`) with `.render_stats(stats, empty_message="Steam-аккаунт не определён — стата недоступна")` (new optional param, defaults to the exact previous hardcoded text so the self-stats caller doesn't need to change), `.show_stats()`, `.hide_stats()`, `.toggle()` (all unchanged).

- [ ] **Step 1: Rename the file and class**

```bash
cd /home/de1zyw/dota_overlay
git mv self_stats_window.py player_stats_window.py
```

In `player_stats_window.py`, change the class declaration:
```python
class SelfStatsWindow(QWidget):
```
to:
```python
class PlayerStatsWindow(QWidget):
```

Update the module docstring's first line from:
```python
"""Dedicated on-demand window showing the local user's own OpenDota stats
```
to:
```python
"""Dedicated on-demand window showing a player's OpenDota stats - used for
both the local user's own stats (self-stats hotkey) and any profile
looked up via OCR. Content is generic; only the caller decides whose
account_id to fetch.
```

- [ ] **Step 2: Add the `empty_message` parameter**

Change:
```python
    def render_stats(self, stats):
        self._clear_layout()

        if stats is None:
            msg = QLabel("Steam-аккаунт не определён — стата недоступна")
```
to:
```python
    def render_stats(self, stats, empty_message="Steam-аккаунт не определён — стата недоступна"):
        self._clear_layout()

        if stats is None:
            msg = QLabel(empty_message)
```

- [ ] **Step 3: Manual verification**

```bash
cd /home/de1zyw/dota_overlay
python3 -c "import ast; ast.parse(open('player_stats_window.py').read())" && echo "syntax OK"
python3 -c "
from player_stats_window import PlayerStatsWindow
print(PlayerStatsWindow)
"
ls self_stats_window.py 2>&1
```
Expected: syntax OK; `PlayerStatsWindow` class prints successfully; the old filename no longer exists (`ls` reports "No such file").

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "refactor: rename SelfStatsWindow to PlayerStatsWindow (now shared with profile lookup)"
```

---

### Task 9: Wire everything into `app.py`

**Files:**
- Modify: `app.py`

**Interfaces:**
- Consumes: `PlayerStatsWindow` (Task 8), `RegionCalibrator` (Task 6), `CandidatePickerWindow` (Task 7), `ocr_capture.capture_region`/`read_nickname` (Task 5), `opendota_client.search_players` (Task 2), `profile_lookup_settings.load`/`save` (Task 1), `profile_lookup_history.append` (Task 1), `HotkeyListener(on_toggle, on_expand, on_self_stats, on_calibrate, on_profile_lookup)` (Task 3).

- [ ] **Step 1: Update imports**

Change:
```python
from opendota_client import fetch_player_stats
from overlay_window import OverlayWindow
from self_stats_window import SelfStatsWindow
```
to:
```python
import profile_lookup_history
import profile_lookup_settings
from candidate_picker_window import CandidatePickerWindow
from ocr_capture import capture_region, read_nickname
from opendota_client import fetch_player_stats, search_players
from overlay_window import OverlayWindow
from player_stats_window import PlayerStatsWindow
from region_calibrator import RegionCalibrator
```

- [ ] **Step 2: Extend `_MainThreadBridge`**

Change the signal list:
```python
    new_match_ready = pyqtSignal(object, object, object, object)
    toggle_visibility_requested = pyqtSignal()
    expand_requested = pyqtSignal()
    self_stats_ready = pyqtSignal(object)
```
to:
```python
    new_match_ready = pyqtSignal(object, object, object, object)
    toggle_visibility_requested = pyqtSignal()
    expand_requested = pyqtSignal()
    self_stats_ready = pyqtSignal(object)
    calibrate_requested = pyqtSignal()
    profile_lookup_ready = pyqtSignal(object)
```

Change `__init__` (rename the `self_stats_window` param/attribute to `player_stats_window`, and connect the 2 new signals):
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
to:
```python
    def __init__(self, window, hide_timer, player_stats_window):
        super().__init__()
        self._window = window
        self._hide_timer = hide_timer
        self._player_stats_window = player_stats_window
        self._active_calibrator = None
        self._active_picker = None
        self.new_match_ready.connect(self._on_new_match_ready)
        self.toggle_visibility_requested.connect(self._on_toggle_visibility)
        self.expand_requested.connect(self._on_expand)
        self.self_stats_ready.connect(self._on_self_stats_ready)
        self.calibrate_requested.connect(self._on_calibrate_requested)
        self.profile_lookup_ready.connect(self._on_profile_lookup_ready)
```

Update `_on_self_stats_ready` (rename the window reference):
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
to:
```python
    def _on_self_stats_ready(self, stats):
        # Always re-fetched on every hotkey press (see OverlayApp.
        # on_self_stats_hotkey below), including the press that's about to
        # close it - a same-account repeat fetch within 30s is served from
        # opendota_client's own cache, so this is cheap, not wasteful.
        if self._player_stats_window.isVisible():
            self._player_stats_window.hide_stats()
        else:
            self._player_stats_window.render_stats(stats)
            self._player_stats_window.show_stats()
```

Add 3 new methods to `_MainThreadBridge` (anywhere among the other `_on_*` methods):
```python
    def _on_calibrate_requested(self):
        event_log.log("HOTKEY", action="calibrate")
        self._active_calibrator = RegionCalibrator(on_done=self._on_calibration_done)

    def _on_calibration_done(self, region):
        event_log.log("CALIBRATION_DONE", region=region)
        self._active_calibrator = None

    def _on_profile_lookup_ready(self, candidates):
        event_log.log("HOTKEY", action="profile_lookup")
        if not candidates:
            self._player_stats_window.render_stats(
                None, empty_message="Профиль не распознан или не найден на OpenDota"
            )
            self._player_stats_window.show_stats()
            return
        if len(candidates) == 1:
            self._show_profile(candidates[0]["account_id"])
        else:
            self._active_picker = CandidatePickerWindow(on_selected=self._on_candidate_selected)
            self._active_picker.show_candidates(candidates)

    def _on_candidate_selected(self, candidate):
        self._active_picker = None
        self._show_profile(candidate["account_id"])

    def _show_profile(self, account_id):
        # Brief main-thread block on this one fetch - acceptable here since
        # it only runs right after an explicit user action (a hotkey press
        # that resolved to exactly one match, or a picker click), not on
        # every poll tick like _poll_picks.
        stats = fetch_player_stats(account_id)
        self._player_stats_window.render_stats(stats)
        self._player_stats_window.show_stats()
        profile_lookup_history.append(account_id, stats.nickname)
```

- [ ] **Step 3: Update `OverlayApp.__init__`**

Change:
```python
        self.window = OverlayWindow()
        self.self_stats_window = SelfStatsWindow()
```
to:
```python
        self.window = OverlayWindow()
        self.player_stats_window = PlayerStatsWindow()
```

Change:
```python
        self.bridge = _MainThreadBridge(self.window, self.hide_timer, self.self_stats_window)
```
to:
```python
        self.bridge = _MainThreadBridge(self.window, self.hide_timer, self.player_stats_window)
```

Change:
```python
        self.hotkeys = HotkeyListener(
            on_toggle=self.bridge.toggle_visibility_requested.emit,
            on_expand=self.bridge.expand_requested.emit,
            on_self_stats=self.on_self_stats_hotkey,
        )
```
to:
```python
        self.hotkeys = HotkeyListener(
            on_toggle=self.bridge.toggle_visibility_requested.emit,
            on_expand=self.bridge.expand_requested.emit,
            on_self_stats=self.on_self_stats_hotkey,
            on_calibrate=self.bridge.calibrate_requested.emit,
            on_profile_lookup=self.on_profile_lookup_hotkey,
        )
```

- [ ] **Step 4: Add `on_profile_lookup_hotkey`**

Add this method to `OverlayApp` right after `on_self_stats_hotkey`:
```python
    def on_profile_lookup_hotkey(self):
        # Runs on pynput's own listener thread - safe to block here on
        # screen capture, OCR, and the network search call. Only the
        # actual window show/hide + render must happen on the main
        # thread, via the bridge signal below.
        region = profile_lookup_settings.load()
        if region is None:
            self.bridge.profile_lookup_ready.emit([])
            return
        image = capture_region(region)
        nickname = read_nickname(image)
        if not nickname:
            self.bridge.profile_lookup_ready.emit([])
            return
        candidates = search_players(nickname)
        self.bridge.profile_lookup_ready.emit(candidates)
```

- [ ] **Step 5: Manual verification**

```bash
cd /home/de1zyw/dota_overlay
python3 -c "import ast; ast.parse(open('app.py').read())" && echo "syntax OK"
python3 -c "import app; print('app.py imports cleanly')"
cp fixtures/server_log_sample.txt /tmp/my_test_log.txt
DISPLAY=:0 QT_QPA_PLATFORM=xcb timeout 15 python3 run_demo.py
```
Expected: syntax check and import both succeed; the demo runs for the full 15s without crashing (pynput hotkeys don't fire in this sandboxed environment per the project's documented limitation, so this step confirms the new wiring didn't break startup - the individual pieces were already verified standalone in Tasks 5-8).

- [ ] **Step 6: Commit**

```bash
rm -f /tmp/my_test_log.txt
git add app.py
git commit -m "feat: wire calibrate + profile-lookup hotkeys into app.py"
```

---

### Task 10: Hub UI - real card + История page

**Files:**
- Modify: `launcher.py`

**Interfaces:**
- Consumes: `launcher_checks.PROFILE_LOOKUP_CHECKS` (Task 4), `profile_lookup_history.load_all()` (Task 1), `opendota_client.fetch_player_stats` (existing, for re-opening a history entry - actually not needed here, the История page only displays past lookups, it doesn't relaunch stats windows since the hub and app.py are separate processes).

- [ ] **Step 1: Import `PROFILE_LOOKUP_CHECKS` and `profile_lookup_history`**

Change:
```python
from launcher_checks import CHECKS, SELF_STATS_CHECKS, STATUS_ERROR, STATUS_OK, STATUS_WARN
```
to:
```python
from launcher_checks import CHECKS, PROFILE_LOOKUP_CHECKS, SELF_STATS_CHECKS, STATUS_ERROR, STATUS_OK, STATUS_WARN
```
Add near the other local imports (alongside `import hotkey_settings`):
```python
import profile_lookup_history
```

- [ ] **Step 2: Move "Профиль по клику" into `OVERLAY_ENTRIES`**

Change:
```python
    {
        "name": "Личная статистика",
        "description": (
            "Своя стата по горячей клавише "
            f"({hotkey_settings.load()['self_stats']}, меняется в НАСТРОЙКИ) — "
            "работает в любой момент, не только на драфте."
        ),
        "checks": SELF_STATS_CHECKS,
        "entry_script": "app.py",
    },
]

# Queued-but-unbuilt features, shown as dimmed placeholder cards so the
# Overlays page reads as a roadmap instead of leaving empty space below the
# real cards.
COMING_SOON_ENTRIES = [
    {
        "name": "Профиль по клику",
        "description": "Показ статы того игрока, чей профиль ты открыл прямо в игре.",
    },
]
```
to:
```python
    {
        "name": "Личная статистика",
        "description": (
            "Своя стата по горячей клавише "
            f"({hotkey_settings.load()['self_stats']}, меняется в НАСТРОЙКИ) — "
            "работает в любой момент, не только на драфте."
        ),
        "checks": SELF_STATS_CHECKS,
        "entry_script": "app.py",
    },
    {
        "name": "Профиль по клику",
        "description": (
            "Открой любой профиль в Доте, нажми "
            f"{hotkey_settings.load()['profile_lookup']} — распознает ник через OCR и "
            "покажет статy. Перед первым использованием откалибруй область "
            f"({hotkey_settings.load()['calibrate']} при открытом профиле)."
        ),
        "checks": PROFILE_LOOKUP_CHECKS,
        "entry_script": "app.py",
    },
]

# Queued-but-unbuilt features, shown as dimmed placeholder cards so the
# Overlays page reads as a roadmap instead of leaving empty space below the
# real cards. Currently empty - kept as a list so a future overlay just
# drops in as one more entry, no structural change needed.
COMING_SOON_ENTRIES = []
```

- [ ] **Step 3: Add `_HistoryPage` class**

Add this class right after `_SettingsPage` (before `class LauncherWindow(QWidget):`):
```python
class _HistoryPage(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        title = QLabel("История просмотренных профилей")
        title.setStyleSheet("color: white; font-weight: bold; font-family: sans-serif; font-size: 14px;")
        layout.addWidget(title)

        self._list = QListWidget()
        self._list.setStyleSheet(
            "QListWidget { background-color: rgba(255,255,255,10); color: white; "
            "font-family: sans-serif; font-size: 12px; border: none; border-radius: 6px; }"
            "QListWidget::item { padding: 6px; }"
        )
        layout.addWidget(self._list)

        self.refresh()

    def refresh(self):
        self._list.clear()
        entries = profile_lookup_history.load_all()
        if not entries:
            self._list.addItem("Пока пусто — историй появится после первого использования «Профиль по клику»")
            return
        for entry in entries:
            self._list.addItem(f"{entry['timestamp']}  —  {entry['nickname']}")
```

- [ ] **Step 4: Add the 4th sidebar entry and page in `LauncherWindow`**

Change:
```python
        self._stack = QStackedWidget()
        overlays_btn = QPushButton("ОВЕРЛЕИ")
        logs_btn = QPushButton("ЛОГИ")
        settings_btn = QPushButton("НАСТРОЙКИ")
        for btn in (overlays_btn, logs_btn, settings_btn):
```
to:
```python
        self._stack = QStackedWidget()
        overlays_btn = QPushButton("ОВЕРЛЕИ")
        logs_btn = QPushButton("ЛОГИ")
        settings_btn = QPushButton("НАСТРОЙКИ")
        history_btn = QPushButton("ИСТОРИЯ")
        for btn in (overlays_btn, logs_btn, settings_btn, history_btn):
```
Change:
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
to:
```python
        nav_buttons = [overlays_btn, logs_btn, settings_btn, history_btn]
        overlays_btn.setChecked(True)
        overlays_btn.clicked.connect(lambda: self._switch_page(0, nav_buttons))
        logs_btn.clicked.connect(lambda: self._switch_page(1, nav_buttons))
        settings_btn.clicked.connect(lambda: self._switch_page(2, nav_buttons))
        history_btn.clicked.connect(lambda: self._switch_page(3, nav_buttons))
        sidebar_layout.addWidget(overlays_btn)
        sidebar_layout.addWidget(logs_btn)
        sidebar_layout.addWidget(settings_btn)
        sidebar_layout.addWidget(history_btn)
        sidebar_layout.addStretch()
```
Change:
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
to:
```python
        self._overlays_page = _OverlaysPage()
        self._logs_page = _LogsPage()
        self._settings_page = _SettingsPage()
        self._history_page = _HistoryPage()
        self._stack.addWidget(self._overlays_page)
        self._stack.addWidget(self._logs_page)
        self._stack.addWidget(self._settings_page)
        self._stack.addWidget(self._history_page)
        content_layout.addWidget(self._stack)
        panel_layout.addWidget(content)

    def _switch_page(self, index, nav_buttons):
        self._stack.setCurrentIndex(index)
        for i, btn in enumerate(nav_buttons):
            btn.setChecked(i == index)
        if index == 1:
            self._logs_page.refresh()
        elif index == 3:
            self._history_page.refresh()
```

- [ ] **Step 5: Manual verification**

```bash
cd /home/de1zyw/dota_overlay
python3 -c "import ast; ast.parse(open('launcher.py').read())" && echo "syntax OK"
rm -f hotkey_settings.json profile_lookup_settings.json profile_lookup_history.json
DISPLAY=:0 QT_QPA_PLATFORM=xcb timeout 30 python3 -u launcher.py
```
Expected: hub opens with 4 sidebar entries (ОВЕРЛЕИ/ЛОГИ/НАСТРОЙКИ/ИСТОРИЯ). ОВЕРЛЕИ now shows 3 real cards (Драфт-статы, Личная статистика, Профиль по клику) and no coming-soon cards; the new "Профиль по клику" card shows its 3 checks (Python deps, tesseract, Область экрана - the last two likely warning/error on this dev machine since tesseract/calibration aren't set up here, which is expected). НАСТРОЙКИ shows 5 hotkey fields now. ИСТОРИЯ shows the empty-state message.

- [ ] **Step 6: Commit**

```bash
git add launcher.py
git commit -m "feat: add real Профиль по клику card and История page to the hub"
```
