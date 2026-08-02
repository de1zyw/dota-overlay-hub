# Overlay Hub Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expand `launcher.py` from a flat checklist into a two-section hub (Overlays / Logs) per the hub design spec, without changing the already-verified check/launch logic.

**Architecture:** New pure-logic `logs_view.py` (parses `logs/run_*.jsonl` into summaries, no Qt). `launcher.py` rewritten around a sidebar + `QStackedWidget`: an Overlays page (today's checklist, now wrapped in a card, driven by a small `OVERLAY_ENTRIES` list) and a new Logs page (list + detail panel built from `logs_view.list_log_runs()`).

**Tech Stack:** Python stdlib (`json`, `os`, `glob`, `subprocess`, `sys`) + PyQt6.

## Global Constraints

- No automated tests — manual verification only.
- Report-only, same as the plain launcher: no auto-fixing, no log deletion.
- `logs_view.list_log_runs()` must never raise on a missing `logs/` dir or a malformed/partial JSONL line.
- Reuse `overlay_window._GradientPanel` and `config.py` color constants for visual consistency.

---

### Task 1: `logs_view.py`

**Files:**
- Create: `logs_view.py`

**Interfaces:**
- Produces: `list_log_runs(log_dir="logs") -> list[dict]`, each dict has keys `path, filename, mtime, size_bytes, event_counts (dict[str,int]), has_error (bool)`. Sorted newest-first by `mtime`. Returns `[]` if `log_dir` doesn't exist.

- [ ] **Step 1: Write `logs_view.py`**

```python
"""Pure parsing of logs/run_*.jsonl files into per-run summaries for the
hub's Logs page - no Qt dependency. Never raises: a missing logs/ dir
returns [], a malformed/partial line (e.g. from a run killed mid-write)
is skipped rather than crashing the whole listing."""
import glob
import json
import os


def _summarize(path):
    event_counts = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)["event"]
            except (json.JSONDecodeError, KeyError):
                continue
            event_counts[event] = event_counts.get(event, 0) + 1

    stat = os.stat(path)
    return {
        "path": path,
        "filename": os.path.basename(path),
        "mtime": stat.st_mtime,
        "size_bytes": stat.st_size,
        "event_counts": event_counts,
        "has_error": event_counts.get("ERROR", 0) > 0,
    }


def list_log_runs(log_dir="logs"):
    if not os.path.isdir(log_dir):
        return []
    runs = [_summarize(p) for p in glob.glob(os.path.join(log_dir, "run_*.jsonl"))]
    runs.sort(key=lambda r: r["mtime"], reverse=True)
    return runs
```

- [ ] **Step 2: Manual verification**

```bash
cd /home/de1zyw/dota_overlay
python3 -c "
from logs_view import list_log_runs
for run in list_log_runs():
    print(run['filename'], run['size_bytes'], 'bytes', 'ERROR' if run['has_error'] else 'ok', run['event_counts'])
print('empty dir case:', list_log_runs('does_not_exist'))
"
```
Expected: one line per existing `logs/run_*.jsonl` file (from earlier manual testing this session) with a plausible event-count dict, plus `empty dir case: []` with no exception.

- [ ] **Step 3: Commit**

```bash
git add logs_view.py
git commit -m "feat: add pure logs/run_*.jsonl summary parsing for the hub"
```

---

### Task 2: Rewrite `launcher.py` as the sidebar hub

**Files:**
- Modify: `launcher.py` (full rewrite of its UI, keeping `_check_item` and the check-driven card logic from the plain launcher)

**Interfaces:**
- Consumes: `launcher_checks.CHECKS/STATUS_*` (existing), `logs_view.list_log_runs` (Task 1), `overlay_window._GradientPanel` (existing).

- [ ] **Step 1: Write the new `launcher.py`**

```python
"""Overlay hub: a sidebar app with an Overlays page (readiness checklist +
launch, per overlay entry) and a Logs page (browse past diagnostic runs).
Same dark-gradient visual style as the overlay itself."""
import os
import subprocess
import sys
from datetime import datetime

from PyQt6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

import config
from launcher_checks import CHECKS, STATUS_ERROR, STATUS_OK, STATUS_WARN
from logs_view import list_log_runs
from overlay_window import _GradientPanel

_STATUS_COLOR = {
    STATUS_OK: config.COLOR_GREEN,
    STATUS_WARN: "#e8b339",
    STATUS_ERROR: config.COLOR_RED,
}
_STATUS_ICON = {STATUS_OK: "✓", STATUS_WARN: "!", STATUS_ERROR: "✗"}

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))

# Data-driven so a second overlay is one more entry, no structural change.
OVERLAY_ENTRIES = [
    {
        "name": "Драфт-статы",
        "description": "Ранг, винрейт, последние матчи и текущий пик союзников/врагов на драфте.",
        "checks": CHECKS,
        "entry_script": "app.py",
    },
]


def _check_item(label, status, message):
    item = QWidget()
    layout = QVBoxLayout(item)
    layout.setContentsMargins(0, 4, 0, 4)
    layout.setSpacing(2)

    header = QWidget()
    header_layout = QHBoxLayout(header)
    header_layout.setContentsMargins(0, 0, 0, 0)
    header_layout.setSpacing(8)

    icon = QLabel(_STATUS_ICON[status])
    icon.setFixedWidth(16)
    icon.setStyleSheet(
        f"color: {_STATUS_COLOR[status]}; font-family: sans-serif; font-weight: bold; font-size: 14px;"
    )
    header_layout.addWidget(icon)

    label_widget = QLabel(label)
    label_widget.setStyleSheet("color: white; font-family: sans-serif; font-size: 13px;")
    header_layout.addWidget(label_widget)
    header_layout.addStretch()
    layout.addWidget(header)

    if status != STATUS_OK:
        detail = QLabel(message)
        detail.setWordWrap(True)
        detail.setStyleSheet("color: #aaaaaa; font-family: sans-serif; font-size: 11px;")
        layout.addWidget(detail)

    return item


class _OverlayCard(QWidget):
    def __init__(self, entry):
        super().__init__()
        self._entry = entry
        self.setStyleSheet(
            "background-color: rgba(255, 255, 255, 12); border-radius: 8px;"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(4)

        header = QHBoxLayout()
        name = QLabel(entry["name"])
        name.setStyleSheet("color: white; font-weight: bold; font-family: sans-serif; font-size: 15px;")
        header.addWidget(name)
        header.addStretch()
        self._status_pill = QLabel("")
        self._status_pill.setStyleSheet("font-family: sans-serif; font-size: 11px; font-weight: bold;")
        header.addWidget(self._status_pill)
        layout.addLayout(header)

        desc = QLabel(entry["description"])
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #aaaaaa; font-family: sans-serif; font-size: 12px;")
        layout.addWidget(desc)

        self._checks_layout = QVBoxLayout()
        self._checks_layout.setContentsMargins(0, 8, 0, 0)
        self._checks_layout.setSpacing(0)
        layout.addLayout(self._checks_layout)

        buttons = QHBoxLayout()
        recheck_btn = QPushButton("Перепроверить")
        recheck_btn.clicked.connect(self.run_checks)
        self._launch_btn = QPushButton("Запустить")
        self._launch_btn.clicked.connect(self._on_launch)
        buttons.addWidget(recheck_btn)
        buttons.addWidget(self._launch_btn)
        layout.addLayout(buttons)

        self.run_checks()

    def run_checks(self):
        while self._checks_layout.count():
            item = self._checks_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        has_error = False
        has_warn = False
        for label, fn in self._entry["checks"]:
            status, message = fn()
            has_error = has_error or status == STATUS_ERROR
            has_warn = has_warn or status == STATUS_WARN
            self._checks_layout.addWidget(_check_item(label, status, message))

        if has_error:
            self._status_pill.setText("НЕ ГОТОВО")
            self._status_pill.setStyleSheet(self._status_pill.styleSheet() + f" color: {config.COLOR_RED};")
        elif has_warn:
            self._status_pill.setText("ЕСТЬ ПРЕДУПРЕЖДЕНИЯ")
            self._status_pill.setStyleSheet(self._status_pill.styleSheet() + " color: #e8b339;")
        else:
            self._status_pill.setText("ГОТОВО")
            self._status_pill.setStyleSheet(self._status_pill.styleSheet() + f" color: {config.COLOR_GREEN};")

        self._launch_btn.setEnabled(not has_error)

    def _on_launch(self):
        subprocess.Popen([sys.executable, self._entry["entry_script"]], cwd=PROJECT_DIR)
        QApplication.instance().quit()


class _OverlaysPage(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        for entry in OVERLAY_ENTRIES:
            layout.addWidget(_OverlayCard(entry))
        layout.addStretch()


class _LogsPage(QWidget):
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

        right = QVBoxLayout()
        self._detail = QLabel("Выбери запуск слева")
        self._detail.setWordWrap(True)
        self._detail.setStyleSheet("color: white; font-family: monospace; font-size: 12px;")
        right.addWidget(self._detail)
        right.addStretch()

        buttons = QHBoxLayout()
        open_folder_btn = QPushButton("Открыть папку с логами")
        open_folder_btn.clicked.connect(self._open_folder)
        copy_path_btn = QPushButton("Скопировать путь")
        copy_path_btn.clicked.connect(self._copy_path)
        buttons.addWidget(open_folder_btn)
        buttons.addWidget(copy_path_btn)
        right.addLayout(buttons)

        right_widget = QWidget()
        right_widget.setLayout(right)
        layout.addWidget(right_widget)

        self._runs = []
        self.refresh()

    def refresh(self):
        self._runs = list_log_runs()
        self._list.clear()
        if not self._runs:
            self._detail.setText("Логов пока нет — запусти оверлей хотя бы раз.")
            return
        for run in self._runs:
            ts = datetime.fromtimestamp(run["mtime"]).strftime("%Y-%m-%d %H:%M:%S")
            prefix = "🔴 " if run["has_error"] else ""
            item = QListWidgetItem(f"{prefix}{ts}")
            self._list.addItem(item)
        self._list.setCurrentRow(0)

    def _on_row_changed(self, row):
        if row < 0 or row >= len(self._runs):
            return
        run = self._runs[row]
        lines = [f"{run['filename']}  ({run['size_bytes']} байт)", ""]
        for event, count in sorted(run["event_counts"].items()):
            lines.append(f"{event}: {count}")
        self._detail.setText("\n".join(lines))

    def _open_folder(self):
        subprocess.Popen(["xdg-open", os.path.join(PROJECT_DIR, "logs")])

    def _copy_path(self):
        row = self._list.currentRow()
        if 0 <= row < len(self._runs):
            QApplication.clipboard().setText(self._runs[row]["path"])


class LauncherWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Dota Overlay Hub")
        self.resize(760, 560)

        self._panel = _GradientPanel()
        panel_layout = QHBoxLayout(self._panel)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        panel_layout.setSpacing(0)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self._panel)

        sidebar = QWidget()
        sidebar.setFixedWidth(160)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(16, 20, 8, 20)
        sidebar_layout.setSpacing(6)

        title = QLabel("DOTA\nOVERLAY HUB")
        title.setStyleSheet(
            "color: white; font-weight: bold; font-family: sans-serif; "
            "font-size: 13px; letter-spacing: 1px;"
        )
        sidebar_layout.addWidget(title)
        sidebar_layout.addSpacing(16)

        self._stack = QStackedWidget()
        overlays_btn = QPushButton("ОВЕРЛЕИ")
        logs_btn = QPushButton("ЛОГИ")
        for btn in (overlays_btn, logs_btn):
            btn.setCheckable(True)
            btn.setStyleSheet(
                "QPushButton { text-align: left; color: #cccccc; background: transparent; "
                "border: none; font-family: sans-serif; font-size: 12px; padding: 8px; }"
                "QPushButton:checked { color: white; font-weight: bold; }"
            )
        overlays_btn.setChecked(True)
        overlays_btn.clicked.connect(lambda: self._switch_page(0, overlays_btn, logs_btn))
        logs_btn.clicked.connect(lambda: self._switch_page(1, overlays_btn, logs_btn))
        sidebar_layout.addWidget(overlays_btn)
        sidebar_layout.addWidget(logs_btn)
        sidebar_layout.addStretch()

        panel_layout.addWidget(sidebar)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(20, 20, 20, 20)
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


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = LauncherWindow()
    window.show()
    sys.exit(app.exec())
```

- [ ] **Step 2: Manual verification**

```bash
cd /home/de1zyw/dota_overlay
DISPLAY=:0 QT_QPA_PLATFORM=xcb python3 launcher.py
```
Expected: a 760×560 window titled "Dota Overlay Hub" with a left sidebar
("ОВЕРЛЕИ" / "ЛОГИ") and the gradient background. On "ОВЕРЛЕИ" (default):
one card "Драфт-статы" with its checklist, status pill, and Launch button
(same values as the plain launcher's already-verified checks). Clicking
"ЛОГИ": a list of past `logs/run_*.jsonl` runs (from this session's
earlier testing) newest first, selecting one shows its event-count
breakdown on the right, "Открыть папку с логами" opens the file manager,
"Скопировать путь" copies a path (paste somewhere to confirm). Click
"Запустить" on the overlay card: hub window closes, `python3 app.py`
starts as a separate process (`ps aux | grep "python3 app.py"`).

- [ ] **Step 3: Commit**

```bash
git add launcher.py
git commit -m "feat: expand launcher into a sidebar hub (overlays + logs pages)"
```
