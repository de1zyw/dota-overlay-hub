"""Overlay hub: a sidebar app with an Overlays page (readiness checklist +
launch, per overlay entry) and a Logs page (browse past diagnostic runs).
Same dark-gradient visual style as the overlay itself."""
import os
import subprocess
import sys
from datetime import datetime

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QIcon
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

import config
import hotkey_settings
from launcher_checks import CHECKS, SELF_STATS_CHECKS, STATUS_ERROR, STATUS_OK, STATUS_WARN
from logs_view import list_log_runs
from overlay_window import _GradientPanel

_STATUS_COLOR = {
    STATUS_OK: config.COLOR_GREEN,
    STATUS_WARN: "#e8b339",
    STATUS_ERROR: config.COLOR_RED,
}

# Same pink/purple/blue gradient recipe as _GradientPanel's own glow, so the
# primary action reads as part of the app's own visual language instead of a
# default system button. Secondary actions stay a subdued translucent panel.
SECONDARY_BUTTON_STYLE = """
QPushButton {
    background-color: rgba(255, 255, 255, 15);
    color: #dddddd;
    border: 1px solid rgba(255, 255, 255, 30);
    border-radius: 6px;
    padding: 8px 16px;
    font-family: sans-serif;
    font-size: 12px;
    font-weight: 600;
}
QPushButton:hover {
    background-color: rgba(255, 255, 255, 25);
    border: 1px solid rgba(255, 255, 255, 50);
}
QPushButton:pressed {
    background-color: rgba(255, 255, 255, 8);
}
"""

PRIMARY_BUTTON_STYLE = """
QPushButton {
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #FF9CE3, stop:0.5 #B388FF, stop:1 #7DD3FC);
    color: #14141a;
    border: none;
    border-radius: 6px;
    padding: 8px 16px;
    font-family: sans-serif;
    font-size: 12px;
    font-weight: 700;
}
QPushButton:hover {
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #ffb3ea, stop:0.5 #c39dff, stop:1 #93ddff);
}
QPushButton:pressed {
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #e080c9, stop:0.5 #9868e0, stop:1 #5cb8e0);
}
QPushButton:disabled {
    background-color: rgba(255, 255, 255, 12);
    color: #666666;
}
"""


def _status_dot(status):
    """A small colored circle with no glyph/text - avoids relying on any
    Unicode symbol (✓/!/✗), which some systems render as colorful emoji
    "stickers" instead of a plain flat icon depending on installed fonts."""
    dot = QLabel()
    dot.setFixedSize(12, 12)
    dot.setStyleSheet(
        f"background-color: {_STATUS_COLOR[status]}; border-radius: 6px;"
    )
    return dot

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))

# Data-driven so a second overlay is one more entry, no structural change.
# Личная статистика shares entry_script="app.py" with Драфт-статы - it's
# the same running process (a hotkey inside app.py), not a separate
# script, so "Запустить" on either card starts the same thing.
OVERLAY_ENTRIES = [
    {
        "name": "Драфт-статы",
        "description": "Ранг, винрейт, последние матчи и текущий пик союзников/врагов на драфте.",
        "checks": CHECKS,
        "entry_script": "app.py",
    },
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


def _check_item(label, status, message):
    # Every widget here gets an explicit "background: transparent;" - without
    # it, Qt style sheets cascade a parent's un-scoped background rule down
    # to every descendant QWidget, which previously made each row show the
    # card's own background as a separate pill behind it instead of sitting
    # flush on the card.
    item = QWidget()
    item.setStyleSheet("background: transparent;")
    layout = QVBoxLayout(item)
    layout.setContentsMargins(0, 4, 0, 4)
    layout.setSpacing(2)

    header = QWidget()
    header.setStyleSheet("background: transparent;")
    header_layout = QHBoxLayout(header)
    header_layout.setContentsMargins(0, 0, 0, 0)
    header_layout.setSpacing(8)

    header_layout.addWidget(_status_dot(status))

    label_widget = QLabel(label)
    label_widget.setStyleSheet("color: white; font-family: sans-serif; font-size: 13px; background: transparent;")
    header_layout.addWidget(label_widget)
    header_layout.addStretch()
    layout.addWidget(header)

    if status != STATUS_OK:
        detail = QLabel(message)
        detail.setWordWrap(True)
        detail.setStyleSheet("color: #aaaaaa; font-family: sans-serif; font-size: 11px; background: transparent;")
        layout.addWidget(detail)

    return item


class _OverlayCard(QWidget):
    def __init__(self, entry):
        super().__init__()
        self._entry = entry
        # Scoped to #overlayCard specifically - an unscoped rule here would
        # cascade down to every descendant QWidget (a well-known Qt style
        # sheet gotcha), which is what caused each check row to show its own
        # copy of this background as a stray pill behind it.
        self.setObjectName("overlayCard")
        self.setStyleSheet(
            "QWidget#overlayCard { background-color: rgba(255, 255, 255, 12); border-radius: 8px; }"
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
        recheck_btn.setStyleSheet(SECONDARY_BUTTON_STYLE)
        recheck_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        recheck_btn.clicked.connect(self.run_checks)
        self._launch_btn = QPushButton("Запустить")
        self._launch_btn.setStyleSheet(PRIMARY_BUTTON_STYLE)
        self._launch_btn.setCursor(Qt.CursorShape.PointingHandCursor)
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

        base_style = "font-family: sans-serif; font-size: 11px; font-weight: bold;"
        if has_error:
            self._status_pill.setText("НЕ ГОТОВО")
            self._status_pill.setStyleSheet(f"{base_style} color: {config.COLOR_RED};")
        elif has_warn:
            self._status_pill.setText("ЕСТЬ ПРЕДУПРЕЖДЕНИЯ")
            self._status_pill.setStyleSheet(f"{base_style} color: #e8b339;")
        else:
            self._status_pill.setText("ГОТОВО")
            self._status_pill.setStyleSheet(f"{base_style} color: {config.COLOR_GREEN};")

        self._launch_btn.setEnabled(not has_error)

    def _on_launch(self):
        subprocess.Popen([sys.executable, self._entry["entry_script"]], cwd=PROJECT_DIR)
        QApplication.instance().quit()


class _ComingSoonCard(QWidget):
    def __init__(self, entry):
        super().__init__()
        self.setObjectName("comingSoonCard")
        self.setStyleSheet(
            "QWidget#comingSoonCard { background-color: rgba(255, 255, 255, 5); border-radius: 8px; "
            "border: 1px dashed rgba(255, 255, 255, 25); }"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(4)

        header = QHBoxLayout()
        name = QLabel(entry["name"])
        name.setStyleSheet("color: #999999; font-weight: bold; font-family: sans-serif; font-size: 15px; background: transparent;")
        header.addWidget(name)
        header.addStretch()
        badge = QLabel("СКОРО")
        badge.setStyleSheet(
            "color: #888888; font-family: sans-serif; font-size: 10px; font-weight: bold; "
            "letter-spacing: 1px; background: transparent;"
        )
        header.addWidget(badge)
        layout.addLayout(header)

        desc = QLabel(entry["description"])
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #666666; font-family: sans-serif; font-size: 12px; background: transparent;")
        layout.addWidget(desc)


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

        right_widget = QWidget()
        right = QVBoxLayout(right_widget)
        right.setContentsMargins(0, 0, 0, 0)

        self._detail = QLabel("Выбери запуск слева")
        self._detail.setWordWrap(True)
        self._detail.setStyleSheet("color: white; font-family: monospace; font-size: 12px;")
        right.addWidget(self._detail)
        right.addStretch()

        buttons = QHBoxLayout()
        open_folder_btn = QPushButton("Открыть папку с логами")
        open_folder_btn.setStyleSheet(SECONDARY_BUTTON_STYLE)
        open_folder_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        open_folder_btn.clicked.connect(self._open_folder)
        copy_path_btn = QPushButton("Скопировать путь")
        copy_path_btn.setStyleSheet(SECONDARY_BUTTON_STYLE)
        copy_path_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        copy_path_btn.clicked.connect(self._copy_path)
        buttons.addWidget(open_folder_btn)
        buttons.addWidget(copy_path_btn)
        right.addLayout(buttons)

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
            item = QListWidgetItem(ts)
            if run["has_error"]:
                # Plain text-color tint, not an emoji marker - avoids the
                # same colorful-"sticker" font-substitution risk as the
                # checklist icons above.
                item.setForeground(QColor(config.COLOR_RED))
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


class _SettingsPage(QWidget):
    _FIELD_LABELS = [
        ("toggle", "Показать/скрыть"),
        ("expand", "Свернуть/развернуть"),
        ("self_stats", "Моя стата"),
        ("calibrate", "Калибровка профиля"),
        ("profile_lookup", "Профиль по клику"),
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

        # Bold accent stripe, Dire-red, echoing overlay_window.py's
        # RADIANT/DIRE color convention - a bit of the overlay's own visual
        # language inside the hub, not just a plain divider line.
        dire_stripe = QFrame()
        dire_stripe.setFixedHeight(4)
        dire_stripe.setStyleSheet(f"background-color: {config.COLOR_RED}; border-radius: 2px;")
        sidebar_layout.addSpacing(8)
        sidebar_layout.addWidget(dire_stripe)
        sidebar_layout.addSpacing(16)

        self._stack = QStackedWidget()
        overlays_btn = QPushButton("ОВЕРЛЕИ")
        logs_btn = QPushButton("ЛОГИ")
        settings_btn = QPushButton("НАСТРОЙКИ")
        for btn in (overlays_btn, logs_btn, settings_btn):
            btn.setCheckable(True)
            btn.setStyleSheet(
                "QPushButton { text-align: left; color: #cccccc; background: transparent; "
                "border: none; font-family: sans-serif; font-size: 12px; padding: 8px; }"
                "QPushButton:checked { color: white; font-weight: bold; }"
            )
        overlays_btn.setChecked(True)
        overlays_btn.clicked.connect(lambda: self._switch_page(0, [overlays_btn, logs_btn, settings_btn]))
        logs_btn.clicked.connect(lambda: self._switch_page(1, [overlays_btn, logs_btn, settings_btn]))
        settings_btn.clicked.connect(lambda: self._switch_page(2, [overlays_btn, logs_btn, settings_btn]))
        sidebar_layout.addWidget(overlays_btn)
        sidebar_layout.addWidget(logs_btn)
        sidebar_layout.addWidget(settings_btn)
        sidebar_layout.addStretch()

        panel_layout.addWidget(sidebar)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(20, 20, 20, 20)
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
