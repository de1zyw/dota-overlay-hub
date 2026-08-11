"""Overlay hub: a sidebar app with an Overlays page (readiness checklist +
launch, per overlay entry) and a Logs page (browse past diagnostic runs).
Same dark-gradient visual style as the overlay itself."""
import os
import sys

# Forces Qt's X11 (XWayland) backend instead of native Wayland - set
# BEFORE any PyQt import triggers platform-plugin selection (that happens
# lazily at QApplication() construction, not at import time, but this is
# set as early as possible to be unambiguous). Root cause: Wayland's own
# protocol gives the COMPOSITOR, not the client, control over where a
# regular toplevel window sits - self.move() on the overlay/stats windows
# (window_position.py) is silently ignored under native Wayland (confirmed
# on this app's own real GNOME/Wayland session - "top right" etc save fine
# but the window stays wherever the compositor auto-placed it). XWayland
# preserves real X11 positioning semantics for XWayland clients, so this
# fixes it without requiring the user to switch their whole login session
# to X11 (which the README's Wayland section already notes as a fallback,
# but forcing this one app to xcb gets the same effect automatically).
# setdefault, not a plain assignment - lets an explicit override (e.g. the
# offscreen-platform test harness used throughout this project) win.
# Linux-only: "xcb" isn't a platform Qt even ships on Windows/macOS - this
# would crash the app on startup there ("could not load the Qt platform
# plugin xcb") if set unconditionally.
if sys.platform.startswith("linux"):
    os.environ.setdefault("QT_QPA_PLATFORM", "xcb")

from datetime import datetime

from PyQt6.QtCore import QEasingCurve, QPropertyAnimation, Qt
from PyQt6.QtGui import QColor, QIcon, QPainter
from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from PyQt6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QStackedWidget,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

import config
import discord_presence
import discord_presence_settings
import hotkey_settings
import mod_language_settings
import mod_manager
import overlay_position_settings
import platform_utils
import profile_lookup_history
from launcher_checks import (
    LAST_MATCH_CHECKS, PROFILE_LOOKUP_CHECKS, SELF_STATS_CHECKS,
    STATUS_ERROR, STATUS_OK, STATUS_WARN,
)
from logs_view import list_log_runs
from mods_page import LANGUAGE_FIELD_STYLE_OK, LANGUAGE_FIELD_STYLE_WARN, _ModsPage
from overlay_window import _GradientPanel
from ui_common import PRIMARY_BUTTON_STYLE, SCROLLBAR_STYLE, SECONDARY_BUTTON_STYLE, Worker

_STATUS_COLOR = {
    STATUS_OK: config.COLOR_GREEN,
    STATUS_WARN: "#e8b339",
    STATUS_ERROR: config.COLOR_RED,
}


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

    _SIZE = 18

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


# Data-driven so a second overlay is one more entry, no structural change.
# Личная статистика shares entry_script="app.py" with Драфт-статы - it's
# the same running process (a hotkey inside app.py), not a separate
# script, so "Запустить" on either card starts the same thing.
OVERLAY_ENTRIES = [
    {
        "name": "Разбор последнего матча",
        "description": (
            "Полный ростер твоего последнего матча с рангом/винрейтом/предметами каждого — "
            f"по хоткею ({hotkey_settings.load()['last_match']}, меняется в НАСТРОЙКИ). "
            "НЕ живой драфт — Dota больше не даёт эти данные во время игры, только после "
            "того как OpenDota обработает матч (может занять время после конца игры)."
        ),
        "checks": LAST_MATCH_CHECKS,
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
    label_widget.setStyleSheet("color: white; font-family: 'Inter'; font-size: 13px; background: transparent;")
    header_layout.addWidget(label_widget, 0, Qt.AlignmentFlag.AlignVCenter)
    header_layout.addStretch()
    layout.addWidget(header)

    if status != STATUS_OK:
        detail = QLabel(message)
        detail.setWordWrap(True)
        detail.setStyleSheet("color: #aaaaaa; font-family: 'Inter'; font-size: 11px; background: transparent;")
        layout.addWidget(detail)

    return item


class _OverlayCard(QWidget):
    def __init__(self, entry, on_launch):
        super().__init__()
        self._entry = entry
        self._on_launch_callback = on_launch
        self._check_worker = None
        # Scoped to #overlayCard specifically - an unscoped rule here would
        # cascade down to every descendant QWidget (a well-known Qt style
        # sheet gotcha), which is what caused each check row to show its own
        # copy of this background as a stray pill behind it.
        self.setObjectName("overlayCard")
        self.setStyleSheet(
            "QWidget#overlayCard { background-color: rgba(255, 255, 255, 12); border-radius: 12px; }"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(4)

        header = QHBoxLayout()
        name = QLabel(entry["name"])
        name.setStyleSheet("color: white; font-weight: bold; font-family: 'Inter'; font-size: 15px;")
        header.addWidget(name)
        header.addStretch()
        self._status_pill = QLabel("")
        self._status_pill.setStyleSheet("font-family: 'Inter'; font-size: 11px; font-weight: bold;")
        header.addWidget(self._status_pill)
        layout.addLayout(header)

        desc = QLabel(entry["description"])
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #aaaaaa; font-family: 'Inter'; font-size: 12px;")
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

    def _clear_checks_layout(self):
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

    def run_checks(self):
        # Some of these checks hit the network (DNS + a live OpenDota
        # request, each with its own multi-second timeout budget) - three
        # cards each running their own checks SYNCHRONOUSLY on the main
        # thread at hub startup is exactly what made the whole window take
        # 2+ seconds to even appear (measured, not assumed). Runs on a
        # background Worker instead; launcher_checks.py's own functions are
        # documented as plain/Qt-free specifically so this is safe.
        self._clear_checks_layout()
        checking_label = QLabel("Проверяю...")
        checking_label.setStyleSheet(
            "color: #888888; font-family: 'Inter'; font-size: 11px; background: transparent;"
        )
        self._checks_layout.addWidget(checking_label)
        self._status_pill.setText("")
        self._launch_btn.setEnabled(False)

        checks = self._entry["checks"]
        self._check_worker = Worker(lambda: [(label, fn()) for label, fn in checks])
        self._check_worker.done.connect(self._on_checks_done)
        self._check_worker.start()

    def _on_checks_done(self, results):
        self._clear_checks_layout()
        if isinstance(results, Exception):
            self._checks_layout.addWidget(_check_item(
                "Проверка", STATUS_ERROR, f"Внутренняя ошибка проверки: {results}",
            ))
            self._status_pill.setText("НЕ ГОТОВО")
            self._status_pill.setStyleSheet(
                f"font-family: 'Inter'; font-size: 11px; font-weight: bold; color: {config.COLOR_RED};"
            )
            self._launch_btn.setEnabled(False)
            return

        has_error = False
        has_warn = False
        for label, (status, message) in results:
            has_error = has_error or status == STATUS_ERROR
            has_warn = has_warn or status == STATUS_WARN
            self._checks_layout.addWidget(_check_item(label, status, message))

        base_style = "font-family: 'Inter'; font-size: 11px; font-weight: bold;"
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
            "QWidget#comingSoonCard { background-color: rgba(255, 255, 255, 5); border-radius: 12px; "
            "border: 1px dashed rgba(255, 255, 255, 25); }"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(4)

        header = QHBoxLayout()
        name = QLabel(entry["name"])
        name.setStyleSheet("color: #999999; font-weight: bold; font-family: 'Inter'; font-size: 15px; background: transparent;")
        header.addWidget(name)
        header.addStretch()
        badge = QLabel("СКОРО")
        badge.setStyleSheet(
            "color: #888888; font-family: 'Inter'; font-size: 10px; font-weight: bold; "
            "letter-spacing: 1px; background: transparent;"
        )
        header.addWidget(badge)
        layout.addLayout(header)

        desc = QLabel(entry["description"])
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #666666; font-family: 'Inter'; font-size: 12px; background: transparent;")
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
            "font-family: 'Inter'; font-size: 12px; border: none; border-radius: 6px; }"
            "QListWidget::item { padding: 6px; }"
            "QListWidget::item:selected { background-color: rgba(255,255,255,30); }"
            + SCROLLBAR_STYLE
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
        platform_utils.open_path(os.path.join(platform_utils.data_dir(), "logs"))

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
        ("last_match", "Разбор последнего матча"),
    ]

    def __init__(self, on_language_changed=None):
        super().__init__()
        self._on_language_changed = on_language_changed
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        title = QLabel("Настройки хоткеев")
        title.setStyleSheet("color: white; font-weight: bold; font-family: 'Inter'; font-size: 14px;")
        layout.addWidget(title)

        current = hotkey_settings.load()
        self._fields = {}
        for key, label_text in self._FIELD_LABELS:
            row = QHBoxLayout()
            label = QLabel(label_text)
            label.setFixedWidth(160)
            label.setStyleSheet("color: #cccccc; font-family: 'Inter'; font-size: 12px;")
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
        self._status_label.setStyleSheet("color: #aaaaaa; font-family: 'Inter'; font-size: 11px;")
        layout.addWidget(self._status_label)

        save_btn = QPushButton("Сохранить")
        save_btn.setStyleSheet(PRIMARY_BUTTON_STYLE)
        save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        save_btn.clicked.connect(self._on_save)
        layout.addWidget(save_btn)

        position_title = QLabel("Расположение оверлея")
        position_title.setStyleSheet(
            "color: white; font-weight: bold; font-family: 'Inter'; font-size: 14px; "
            "margin-top: 12px;"
        )
        layout.addWidget(position_title)

        current_position = overlay_position_settings.load()
        self._position_group = QButtonGroup(self)
        self._position_status_label = QLabel("")
        self._position_status_label.setStyleSheet("color: #aaaaaa; font-family: 'Inter'; font-size: 11px;")
        for position in overlay_position_settings.POSITIONS:
            radio = QRadioButton(overlay_position_settings.POSITION_LABELS[position])
            radio.setStyleSheet("color: #cccccc; font-family: 'Inter'; font-size: 12px;")
            radio.setChecked(position == current_position)
            radio.toggled.connect(lambda checked, p=position: self._on_position_toggled(checked, p))
            self._position_group.addButton(radio)
            layout.addWidget(radio)
        layout.addWidget(self._position_status_label)

        language_title = QLabel("Язык модов")
        language_title.setStyleSheet(
            "color: white; font-weight: bold; font-family: 'Inter'; font-size: 14px; "
            "margin-top: 12px;"
        )
        layout.addWidget(language_title)

        language_hint = QLabel(
            "-language, в папку которого ставятся моды (и Minify, если он есть). Valve "
            "заблокировала кастомные значения (123, minify и т.п.) — работают только "
            "официальные языки Dota (russian, english, ...). Даже для английской Dota "
            "надёжнее russian — эта папка точно поддерживается."
        )
        language_hint.setWordWrap(True)
        language_hint.setStyleSheet("color: #888888; font-family: 'Inter'; font-size: 11px;")
        layout.addWidget(language_hint)

        language_row = QHBoxLayout()
        language_id_label = QLabel("-language")
        language_id_label.setFixedWidth(160)
        language_id_label.setStyleSheet("color: #cccccc; font-family: 'Inter'; font-size: 12px;")
        language_row.addWidget(language_id_label)
        self._language_field = QLineEdit(mod_manager.get_language())
        self._language_field.setStyleSheet(
            LANGUAGE_FIELD_STYLE_OK
            if mod_language_settings.is_official(mod_manager.get_language())
            else LANGUAGE_FIELD_STYLE_WARN
        )
        language_row.addWidget(self._language_field)
        layout.addLayout(language_row)

        self._language_status_label = QLabel("")
        self._language_status_label.setStyleSheet("color: #aaaaaa; font-family: 'Inter'; font-size: 11px;")
        layout.addWidget(self._language_status_label)

        language_save_btn = QPushButton("Сохранить")
        language_save_btn.setStyleSheet(PRIMARY_BUTTON_STYLE)
        language_save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        language_save_btn.clicked.connect(self._on_save_language)
        layout.addWidget(language_save_btn)

        discord_title = QLabel("Discord Rich Presence")
        discord_title.setStyleSheet(
            "color: white; font-weight: bold; font-family: 'Inter'; font-size: 14px; "
            "margin-top: 12px;"
        )
        layout.addWidget(discord_title)

        discord_hint = QLabel(
            "Показывает в твоём Discord-профиле, что открыт Dota Overlay Hub. Нужен свой "
            "Client ID: discord.com/developers/applications → New Application → скопируй "
            "\"Application ID\" со страницы General Information."
        )
        discord_hint.setWordWrap(True)
        discord_hint.setStyleSheet("color: #888888; font-family: 'Inter'; font-size: 11px;")
        layout.addWidget(discord_hint)

        discord_settings = discord_presence_settings.load()
        self._discord_enabled_checkbox = QCheckBox("Включить")
        self._discord_enabled_checkbox.setStyleSheet(
            "color: #cccccc; font-family: 'Inter'; font-size: 12px;"
        )
        self._discord_enabled_checkbox.setChecked(discord_settings["enabled"])
        layout.addWidget(self._discord_enabled_checkbox)

        discord_row = QHBoxLayout()
        discord_id_label = QLabel("Client ID")
        discord_id_label.setFixedWidth(160)
        discord_id_label.setStyleSheet("color: #cccccc; font-family: 'Inter'; font-size: 12px;")
        discord_row.addWidget(discord_id_label)
        self._discord_client_id_field = QLineEdit(discord_settings["client_id"])
        self._discord_client_id_field.setPlaceholderText("например 1234567890123456789")
        self._discord_client_id_field.setStyleSheet(
            "QLineEdit { background-color: rgba(255,255,255,10); color: white; "
            "border: 1px solid rgba(255,255,255,30); border-radius: 4px; padding: 4px 8px; "
            "font-family: monospace; font-size: 12px; }"
        )
        discord_row.addWidget(self._discord_client_id_field)
        layout.addLayout(discord_row)

        self._discord_status_label = QLabel(
            "" if discord_presence.available() else "Не установлен пакет pypresence"
        )
        self._discord_status_label.setStyleSheet("color: #aaaaaa; font-family: 'Inter'; font-size: 11px;")
        layout.addWidget(self._discord_status_label)

        discord_save_btn = QPushButton("Сохранить")
        discord_save_btn.setStyleSheet(PRIMARY_BUTTON_STYLE)
        discord_save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        discord_save_btn.clicked.connect(self._on_save_discord)
        layout.addWidget(discord_save_btn)

        layout.addStretch()

    def _on_save_language(self):
        new_language = self._language_field.text().strip()
        if new_language == mod_manager.get_language():
            return
        if not mod_language_settings.is_valid(new_language):
            self._language_status_label.setText(
                "Недопустимое имя (буквы/цифры/дефис/подчёркивание, до 32 символов)"
            )
            return
        installed_count = len(mod_manager.list_installed())
        migrate = True
        if installed_count:
            choice = QMessageBox.question(
                self, "Смена языка модов",
                f"Сейчас через менеджер установлено модов: {installed_count}. Перенести их файлы "
                f"в новую папку dota_{new_language}? Если нет — они останутся в старой папке, но "
                "менеджер перестанет их отслеживать (кнопка «Удалить» перестанет их видеть).",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                | QMessageBox.StandardButton.Cancel,
            )
            if choice == QMessageBox.StandardButton.Cancel:
                return
            migrate = choice == QMessageBox.StandardButton.Yes
        ok, message = mod_manager.set_language(new_language, migrate=migrate)
        if ok and not mod_language_settings.is_official(new_language):
            message += " — ⚠ не официальный язык, Valve может это блокировать, надёжнее russian"
        self._language_status_label.setText(message)
        if ok:
            self._language_field.setStyleSheet(
                LANGUAGE_FIELD_STYLE_OK
                if mod_language_settings.is_official(new_language)
                else LANGUAGE_FIELD_STYLE_WARN
            )
            if self._on_language_changed:
                self._on_language_changed()

    def _on_save_discord(self):
        enabled = self._discord_enabled_checkbox.isChecked()
        client_id = self._discord_client_id_field.text().strip()
        if enabled and not discord_presence_settings.is_valid_client_id(client_id):
            self._discord_status_label.setText("Client ID выглядит неправильным (только цифры, 15-25 знаков)")
            return
        ok = discord_presence_settings.save(enabled, client_id)
        if ok and enabled:
            discord_presence.update_async("Dota Overlay Hub", "В хабе")
        elif ok and not enabled:
            discord_presence.clear_async()
        self._discord_status_label.setText("Сохранено" if ok else "Не удалось сохранить")

    def _on_position_toggled(self, checked, position):
        if not checked:
            return
        # Applies live to the next show()/render, no relaunch needed -
        # unlike hotkeys, which pynput only binds once at startup.
        ok = overlay_position_settings.save(position)
        self._position_status_label.setText(
            "Сохранено — применится при следующем показе оверлея" if ok else "Не удалось сохранить"
        )

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
            "font-family: 'Inter'; font-size: 12px; border: none; border-radius: 6px; }"
            "QListWidget::item { padding: 6px; }"
            "QListWidget::item:selected { background-color: rgba(255,255,255,30); }"
            + SCROLLBAR_STYLE
        )
        self._list.currentRowChanged.connect(self._on_row_changed)
        layout.addWidget(self._list)

        self._detail = QLabel("Выбери запись слева")
        self._detail.setWordWrap(True)
        self._detail.setTextFormat(Qt.TextFormat.RichText)
        self._detail.setOpenExternalLinks(True)
        self._detail.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._detail.setStyleSheet("color: white; font-family: 'Inter'; font-size: 12px;")
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
        # This has broken twice now, both times as "status dots render as a
        # hard-clipped half-moon instead of a full circle" - and both times
        # the real cause was WIDTH, not height, despite how it looks: too
        # narrow a window wraps the longer warning/error lines onto extra
        # rows, and _StatusDot's fixed size gets compressed along with
        # everything else once the layout can't fit every row's true
        # preferred height. A QScrollArea around the Overlays page (below)
        # only helps once rows stop being squeezed in the first place - it
        # can't rescue a widget that already reported a shrunk size. 1200
        # confirmed wide enough for every check message's current length
        # (including the [0x1234]-style codes in error_codes.py, which push
        # several of these lines close to wrapping); 760 keeps the window
        # inside a 1280x800 screen with room to spare.
        self.resize(1200, 760)

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
            "color: white; font-weight: bold; font-family: 'Inter'; "
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
        mods_btn = QPushButton("МОДЫ")
        logs_btn = QPushButton("ЛОГИ")
        settings_btn = QPushButton("НАСТРОЙКИ")
        history_btn = QPushButton("ИСТОРИЯ")
        for btn in (overlays_btn, mods_btn, logs_btn, settings_btn, history_btn):
            btn.setCheckable(True)
            btn.setStyleSheet(
                "QPushButton { text-align: left; color: #cccccc; background: transparent; "
                "border: none; font-family: 'Inter'; font-size: 12px; padding: 8px; }"
                "QPushButton:checked { color: white; font-weight: bold; }"
            )
        nav_buttons = [overlays_btn, mods_btn, logs_btn, settings_btn, history_btn]
        overlays_btn.setChecked(True)
        overlays_btn.clicked.connect(lambda: self._switch_page(0, nav_buttons))
        mods_btn.clicked.connect(lambda: self._switch_page(1, nav_buttons))
        logs_btn.clicked.connect(lambda: self._switch_page(2, nav_buttons))
        settings_btn.clicked.connect(lambda: self._switch_page(3, nav_buttons))
        history_btn.clicked.connect(lambda: self._switch_page(4, nav_buttons))
        sidebar_layout.addWidget(overlays_btn)
        sidebar_layout.addWidget(mods_btn)
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
        # Scrolls instead of relying on the window being tall enough to fit
        # every check for every card - the previous fix for this exact bug
        # (dots painting as a hard-clipped half-moon under cramped vertical
        # space) was just resizing the window to a height that happened to
        # fit the checklists that existed at the time. Every check added
        # since then re-shrinks that margin; a scroll area can't run out of
        # room no matter how many checks a future card ends up with.
        overlays_scroll = QScrollArea()
        overlays_scroll.setWidget(self._overlays_page)
        overlays_scroll.setWidgetResizable(True)
        overlays_scroll.setFrameShape(QFrame.Shape.NoFrame)
        overlays_scroll.setStyleSheet(
            "QScrollArea { background: transparent; } "
            "QScrollArea > QWidget > QWidget { background: transparent; }"
            + SCROLLBAR_STYLE
        )
        self._mods_page = _ModsPage()
        self._logs_page = _LogsPage()
        self._settings_page = _SettingsPage(on_language_changed=self._mods_page._refresh_footer)
        self._history_page = _HistoryPage()
        self._stack.addWidget(overlays_scroll)
        self._stack.addWidget(self._mods_page)
        self._stack.addWidget(self._logs_page)
        self._stack.addWidget(self._settings_page)
        self._stack.addWidget(self._history_page)
        content_layout.addWidget(self._stack)
        panel_layout.addWidget(content)

        # Fade the page content in on every switch - a plain instant
        # setCurrentIndex() felt flat given how much visual polish the rest
        # of the app already has. QGraphicsOpacityEffect is the standard
        # PyQt way to animate a widget's opacity (QStackedWidget itself has
        # no built-in transition support).
        self._stack_opacity = QGraphicsOpacityEffect(self._stack)
        self._stack.setGraphicsEffect(self._stack_opacity)
        self._fade_anim = QPropertyAnimation(self._stack_opacity, b"opacity", self)
        self._fade_anim.setDuration(180)
        self._fade_anim.setStartValue(0.0)
        self._fade_anim.setEndValue(1.0)
        self._fade_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._setup_tray_icon()

    def _switch_page(self, index, nav_buttons):
        self._stack.setCurrentIndex(index)
        for i, btn in enumerate(nav_buttons):
            btn.setChecked(i == index)
        self._fade_anim.stop()
        self._fade_anim.start()
        if index == 2:
            self._logs_page.refresh()
        elif index == 4:
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
        # Used to hide() here to tuck the hub away into the tray - but on
        # DEs where the tray icon doesn't render (common on several Linux
        # setups), that left no way back to the hub at all. Keep it open;
        # all 3 overlay cards share this same running process anyway (see
        # OVERLAY_ENTRIES's comment), so there's nothing left to "launch"
        # by revisiting other cards - the hub staying open is pure upside.

    def closeEvent(self, event):
        event.ignore()
        self.hide()

    def _setup_tray_icon(self):
        self._tray_icon = QSystemTrayIcon(QIcon(platform_utils.resource_path("icon.png")), self)
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

    def _on_activation_request(self):
        # Fired when a second `python3 launcher.py` (or desktop-entry
        # launch) attempt connects to our single-instance socket instead
        # of starting its own process. On DEs where the tray icon doesn't
        # render, this is the only way back to a hidden hub window - just
        # relaunch the app and it raises the existing one instead of
        # showing a dead-end "already running" message.
        conn = self._single_instance_server.nextPendingConnection()
        if conn:
            conn.disconnectFromServer()
        self._show_from_tray()


_SINGLE_INSTANCE_KEY = "dota-overlay-hub-single-instance"


def _acquire_single_instance():
    """Returns a listening QLocalServer if this is the only running
    instance, or None if another one already holds the key. Connecting
    first (rather than just trying to listen) distinguishes "another
    instance is alive" from "a stale socket file was left behind by a
    crashed previous run" - in the latter case connectToServer() fails
    and removeServer() clears the stale file before we listen ourselves."""
    socket = QLocalSocket()
    socket.connectToServer(_SINGLE_INSTANCE_KEY)
    if socket.waitForConnected(200):
        socket.disconnectFromServer()
        return None
    QLocalServer.removeServer(_SINGLE_INSTANCE_KEY)
    server = QLocalServer()
    server.listen(_SINGLE_INSTANCE_KEY)
    return server


if __name__ == "__main__":
    app = QApplication(sys.argv)
    import fonts
    app.setFont(fonts.default_font())
    # Ties this running process to dota-overlay-hub.desktop by name, so the
    # taskbar/dock can look up that entry's Icon= instead of falling back to
    # a generic icon when it can't otherwise correlate the window to it.
    app.setDesktopFileName("dota-overlay-hub")
    app.setWindowIcon(QIcon(platform_utils.resource_path("icon.png")))
    # This is now a tray-resident app - closing/hiding every window must not
    # exit the process; only the tray menu's "Выйти" (or Ctrl+C) should.
    app.setQuitOnLastWindowClosed(False)

    single_instance_server = _acquire_single_instance()
    if single_instance_server is None:
        # Another instance is already running - the connectToServer() call
        # inside _acquire_single_instance() just now IS the ping; that
        # instance's newConnection handler (wired up below) will raise its
        # window in response. Nothing left to do here.
        sys.exit(0)

    window = LauncherWindow()
    window._single_instance_server = single_instance_server
    single_instance_server.newConnection.connect(window._on_activation_request)
    window.show()
    sys.exit(app.exec())
