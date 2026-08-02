"""Overlay hub: a sidebar app with an Overlays page (readiness checklist +
launch, per overlay entry) and a Logs page (browse past diagnostic runs).
Same dark-gradient visual style as the overlay itself."""
import os
import subprocess
import sys
from datetime import datetime

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QIcon, QPainter
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QStackedWidget,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

import config
import hotkey_settings
import profile_lookup_history
from launcher_checks import CHECKS, PROFILE_LOOKUP_CHECKS, SELF_STATS_CHECKS, STATUS_ERROR, STATUS_OK, STATUS_WARN
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


class _StatusDot(QWidget):
    """A small colored circle with no glyph/text - avoids relying on any
    Unicode symbol (✓/!/✗), which some systems render as colorful emoji
    "stickers" instead of a plain flat icon depending on installed fonts.
    Paints itself directly in paintEvent using its own current rect,
    rather than a QLabel showing a fixed-size pixmap or a QSS
    background-color+border-radius - both of those rendered as a half-moon
    (flat-cut bottom) specifically when placed inside the hub's full
    sidebar+QStackedWidget window (reproduced via QWidget.grab(), so not
    an X11/screenshot-tool artifact - some real Qt layout interaction in
    that specific context clipped the label/pixmap's visible height).
    A self-painting widget can't be clipped this way: paintEvent always
    draws an ellipse inscribed in whatever rect the widget actually has."""

    _SIZE = 12

    def __init__(self, status):
        super().__init__()
        self._color = QColor(_STATUS_COLOR[status])
        self.setFixedSize(self._SIZE, self._SIZE)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self._color)
        painter.drawEllipse(self.rect())


def _status_dot(status):
    return _StatusDot(status)

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
    {
        "name": "Профиль по клику",
        "description": (
            "Открой любой профиль в Доте, нажми "
            f"{hotkey_settings.load()['profile_lookup']} — распознает ник через OCR и "
            "покажет стату. Перед первым использованием откалибруй область "
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

    # AlignVCenter on the fixed-size dot specifically - without it, Qt
    # top-aligns the 12px dot within the row's full height (set by the
    # label's font line-height), so the dot sat visibly higher than the
    # label's text, looking like the text had slid down relative to it.
    header_layout.addWidget(_status_dot(status), 0, Qt.AlignmentFlag.AlignVCenter)

    label_widget = QLabel(label)
    label_widget.setStyleSheet("color: white; font-family: sans-serif; font-size: 13px; background: transparent;")
    header_layout.addWidget(label_widget, 0, Qt.AlignmentFlag.AlignVCenter)
    header_layout.addStretch()
    layout.addWidget(header)

    if status != STATUS_OK:
        detail = QLabel(message)
        detail.setWordWrap(True)
        detail.setStyleSheet("color: #aaaaaa; font-family: sans-serif; font-size: 11px; background: transparent;")
        layout.addWidget(detail)

    return item


class _OverlayCard(QWidget):
    def __init__(self, entry, on_launch):
        super().__init__()
        self._entry = entry
        self._on_launch_callback = on_launch
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
                # hide() first, not just deleteLater(): takeAt() only
                # removes the widget from the LAYOUT's bookkeeping, it stays
                # visible at its old geometry until Qt actually processes
                # the deferred deleteLater() on a later event-loop tick - in
                # between, it briefly overlapped the newly-added row at the
                # same position, showing as ghosted/doubled text.
                widget.hide()
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
        self._on_launch_callback()


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


def _card_divider():
    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setFixedHeight(1)
    line.setStyleSheet("background-color: rgba(255, 255, 255, 20); border: none;")
    return line


class _OverlaysPage(QWidget):
    def __init__(self, on_launch):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        all_entries = [(entry, _OverlayCard) for entry in OVERLAY_ENTRIES] + \
            [(entry, _ComingSoonCard) for entry in COMING_SOON_ENTRIES]
        for i, (entry, card_cls) in enumerate(all_entries):
            if i > 0:
                layout.addWidget(_card_divider())
            layout.addWidget(card_cls(entry, on_launch) if card_cls is _OverlayCard else card_cls(entry))
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
        history_btn = QPushButton("ИСТОРИЯ")
        for btn in (overlays_btn, logs_btn, settings_btn, history_btn):
            btn.setCheckable(True)
            btn.setStyleSheet(
                "QPushButton { text-align: left; color: #cccccc; background: transparent; "
                "border: none; font-family: sans-serif; font-size: 12px; padding: 8px; }"
                "QPushButton:checked { color: white; font-weight: bold; }"
            )
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

        panel_layout.addWidget(sidebar)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(20, 20, 20, 20)
        self._overlay_app = None
        self._overlays_page = _OverlaysPage(on_launch=self.start_overlay_and_hide)
        self._logs_page = _LogsPage()
        self._settings_page = _SettingsPage()
        self._history_page = _HistoryPage()
        self._stack.addWidget(self._overlays_page)
        self._stack.addWidget(self._logs_page)
        self._stack.addWidget(self._settings_page)
        self._stack.addWidget(self._history_page)
        content_layout.addWidget(self._stack)
        panel_layout.addWidget(content)

        self._setup_tray_icon()

    def _switch_page(self, index, nav_buttons):
        self._stack.setCurrentIndex(index)
        for i, btn in enumerate(nav_buttons):
            btn.setChecked(i == index)
        if index == 1:
            self._logs_page.refresh()
        elif index == 3:
            self._history_page.refresh()

    def start_overlay_and_hide(self):
        if self._overlay_app is None:
            from app import OverlayApp
            try:
                self._overlay_app = OverlayApp()
                self._overlay_app.start_services()
            except Exception:
                # This now runs inside the hub's own tray-resident process -
                # an unhandled exception here would take down the whole
                # process (hub + tray icon), not just a throwaway subprocess
                # like before the single-process merge. Keep the hub alive
                # and visible so the user can see something went wrong
                # instead of the app just vanishing.
                self._overlay_app = None
                return
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
