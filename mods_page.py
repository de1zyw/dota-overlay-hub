"""МОДЫ tab: browses the open Dota2PornFx mod catalog (mod_catalog.py) and
installs/removes cosmetic mods via mod_manager.py. Layout borrows the
official Dota2PornFx Mod Manager's visual language (grouped sidebar with
counts, a "recently added" carousel, big category tiles, a persistent
status footer) but reskinned entirely in this app's own dark/pink-purple-
blue palette (ui_common.py) - none of their colors, just their structure.

Preview downloads and install/uninstall both hit the network - each runs
on its own throwaway QThread so neither ever blocks the Qt event loop.

Mods can be installed one at a time (each card's own button) or picked
via checkbox across any number of categories and installed in one batch
run - the batch queue survives switching categories (tracked in
_ModsPage._selected, keyed by (category_id, mod_name), independent of any
one _ModCard's lifetime since the grid is rebuilt on every category/search
change)."""
import os
import subprocess

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QFrame, QGridLayout, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton,
    QScrollArea, QStackedWidget, QVBoxLayout, QWidget,
)

import mod_catalog
import mod_language_settings
import mod_manager
from tools_panel import _ToolsPanel
from ui_common import PRIMARY_BUTTON_STYLE, SECONDARY_BUTTON_STYLE
from ui_common import Worker as _Worker

# The OS toggle's "active platform" pill - same gradient as PRIMARY so it
# reads as "this one's selected", vs. the plain SECONDARY look of an
# available-but-not-selected option.
OS_ACTIVE_STYLE = PRIMARY_BUTTON_STYLE
# Windows has no install backend yet (mod_manager.py only knows how to find
# a LINUX Steam library - see steam_library.py) - shown, not hidden, so the
# roadmap is visible, but disabled so it can't be picked. Qt's own
# :disabled state (SECONDARY_BUTTON_STYLE already defines one) is exactly
# the "greyed out / behind glass" look this needs, no extra style required.
OS_LOCKED_STYLE = SECONDARY_BUTTON_STYLE

# Qt's platform-default checkbox indicator is nearly invisible against this
# app's dark custom background (no explicit style = whatever the barely-
# there system default happens to be) - drawn explicitly here, same
# gradient-on-check language as the primary button, so "selected for
# batch install" actually reads as selected.
CHECKBOX_STYLE = """
QCheckBox { background: transparent; spacing: 4px; }
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border: 1px solid rgba(255, 255, 255, 70);
    border-radius: 3px;
    background-color: rgba(255, 255, 255, 12);
}
QCheckBox::indicator:hover { border: 1px solid rgba(255, 255, 255, 120); }
QCheckBox::indicator:checked {
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #FF9CE3, stop:0.5 #B388FF, stop:1 #7DD3FC);
    border: 1px solid rgba(255, 255, 255, 120);
}
QCheckBox::indicator:disabled {
    background-color: rgba(255, 255, 255, 4);
    border: 1px solid rgba(255, 255, 255, 20);
}
"""

# Categories run from ~30 up to 464 mods (heroes) - rendering every card at
# once would mean hundreds of concurrent thumbnail downloads and a very
# tall scroll area. Capped, with the true count always shown below the
# grid so a truncated category still reads as "search to narrow", not as
# "this is everything".
MODS_PER_PAGE = 60
CARD_WIDTH = 150
PREVIEW_HEIGHT = 100
GRID_COLUMNS = 4

# Purely a sidebar grouping label - the catalog itself has no group/section
# concept beyond the flat category list, this mirrors the official Mod
# Manager's ГЕРОИ/МИР/ЭФФЕКТЫ/etc sidebar sections for readability. Any
# category not listed here (e.g. a new one the catalog adds later) falls
# through to "ПРОЧЕЕ" rather than silently vanishing from the sidebar.
_CATEGORY_GROUPS = {
    "heroes": "ГЕРОИ", "hero-items": "ГЕРОИ", "herofx": "ГЕРОИ", "hero-sounds": "ГЕРОИ",
    "terrains": "МИР", "trees": "МИР", "river": "МИР", "roshan": "МИР",
    "ancient": "МИР", "tormentor": "МИР", "towers": "МИР", "wards": "МИР",
    "couriers": "МИР", "creeps": "МИР", "creep-deny": "МИР", "backgrounds": "МИР",
    "versus-screens": "МИР", "huds": "МИР", "pedestal": "МИР",
    "shaders": "ЭФФЕКТЫ", "ti-bp-effects": "ЭФФЕКТЫ", "item-effects": "ЭФФЕКТЫ",
    "ranged-attack": "ЭФФЕКТЫ", "pings": "ЭФФЕКТЫ", "mega-kill": "ЭФФЕКТЫ",
    "high-five": "ЭФФЕКТЫ",
    "sounds": "АУДИО", "announcers": "АУДИО", "music": "АУДИО",
}
_GROUP_ORDER = ["ГЕРОИ", "МИР", "ЭФФЕКТЫ", "АУДИО", "ПРОЧЕЕ"]
_FALLBACK_GROUP = "ПРОЧЕЕ"

TILE_WIDTH = 200
TILE_HEIGHT = 120
TILE_COLUMNS = 4
RECENT_CARD_WIDTH = 150
RECENT_CARD_IMAGE_HEIGHT = 90
RECENT_LIMIT = 12

LANGUAGE_FIELD_STYLE_OK = (
    "QLineEdit { background-color: rgba(255,255,255,10); color: white; "
    "border: 1px solid rgba(255,255,255,30); border-radius: 4px; padding: 4px 8px; "
    "font-family: monospace; font-size: 11px; }"
)
# Non-official -language values are flagged, not blocked outright - Valve's
# exact allow-list isn't published anywhere authoritative, so this is a
# "you're on your own if you keep this" warning, not a hard validation
# rule (mod_language_settings.is_valid() already covers actual syntax).
LANGUAGE_FIELD_STYLE_WARN = (
    "QLineEdit { background-color: rgba(226,87,76,25); color: white; "
    "border: 1px solid #e2574c; border-radius: 4px; padding: 4px 8px; "
    "font-family: monospace; font-size: 11px; }"
)


class _BatchInstallWorker(QThread):
    """Installs a queue of (category_id, mod) jobs one at a time, on one
    background thread - sequential on purpose: mod_manager's manifest file
    is a plain read-modify-write JSON file, not safe for concurrent
    installs to touch at once."""
    progress = pyqtSignal(int, int, str, bool)  # done_count, total, mod_name, ok
    finished_all = pyqtSignal()

    def __init__(self, jobs, parent=None):
        super().__init__(parent)
        self._jobs = jobs

    def run(self):
        total = len(self._jobs)
        for i, (category_id, mod) in enumerate(self._jobs, start=1):
            try:
                ok, _message = mod_manager.install_mod(category_id, mod)
            except Exception:  # noqa: BLE001 - one bad mod shouldn't kill the queue
                ok = False
            self.progress.emit(i, total, mod["name"], ok)
        self.finished_all.emit()


class _ModCard(QFrame):
    def __init__(self, category_id, mod, checked, on_toggle):
        super().__init__()
        self._category_id = category_id
        self._mod = mod
        self._on_toggle = on_toggle
        self._preview_worker = None
        self._action_worker = None

        self.setObjectName("modCard")
        self.setStyleSheet(
            "QFrame#modCard { background-color: rgba(255,255,255,10); border-radius: 12px; }"
        )
        self.setFixedWidth(CARD_WIDTH)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        top_row = QHBoxLayout()
        top_row.setSpacing(4)
        self._checkbox = QCheckBox()
        self._checkbox.setChecked(checked)
        self._checkbox.setStyleSheet(CHECKBOX_STYLE)
        self._checkbox.setCursor(Qt.CursorShape.PointingHandCursor)
        self._checkbox.toggled.connect(self._on_checkbox_toggled)
        top_row.addWidget(self._checkbox, 0, Qt.AlignmentFlag.AlignTop)
        name = QLabel(mod["name"])
        name.setWordWrap(True)
        name.setStyleSheet(
            "color: white; font-family: 'Inter'; font-size: 11px; "
            "font-weight: 600; background: transparent;"
        )
        top_row.addWidget(name, 1)
        layout.addLayout(top_row)

        self._preview_label = QLabel()
        self._preview_label.setFixedSize(CARD_WIDTH - 16, PREVIEW_HEIGHT)
        self._preview_label.setStyleSheet(
            "background-color: rgba(0,0,0,60); border-radius: 4px;"
        )
        self._preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._preview_label)

        self._action_btn = QPushButton()
        self._action_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._action_btn.clicked.connect(self._on_action_clicked)
        layout.addWidget(self._action_btn)

        self._status_label = QLabel("")
        self._status_label.setWordWrap(True)
        self._status_label.setStyleSheet(
            "color: #999999; font-family: 'Inter'; font-size: 10px; background: transparent;"
        )
        layout.addWidget(self._status_label)

        self._refresh_button_state()
        self._load_preview()

    def _refresh_button_state(self):
        installed = mod_manager.is_installed(self._category_id, self._mod["name"])
        self._action_btn.setText("Удалить" if installed else "Установить")
        self._action_btn.setStyleSheet(SECONDARY_BUTTON_STYLE if installed else PRIMARY_BUTTON_STYLE)
        # No point queueing an already-installed mod for the batch button -
        # its own "Удалить" already covers that case.
        self._checkbox.setEnabled(not installed)
        if installed:
            self._checkbox.setChecked(False)

    def _on_checkbox_toggled(self, checked):
        self._on_toggle(self._category_id, self._mod, checked)

    def _load_preview(self):
        preview = self._mod.get("preview")
        if not preview:
            return
        self._preview_worker = _Worker(
            lambda: mod_catalog.get_preview_path(self._category_id, preview)
        )
        self._preview_worker.done.connect(self._on_preview_loaded)
        self._preview_worker.start()

    def _on_preview_loaded(self, path):
        if not isinstance(path, str) or not os.path.exists(path):
            return
        pixmap = QPixmap(path)
        if pixmap.isNull():
            return
        scaled = pixmap.scaled(
            self._preview_label.width(), self._preview_label.height(),
            Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation,
        )
        self._preview_label.setPixmap(scaled)

    def _on_action_clicked(self):
        self._action_btn.setEnabled(False)
        installed = mod_manager.is_installed(self._category_id, self._mod["name"])
        if installed:
            fn = lambda: mod_manager.uninstall_mod(self._category_id, self._mod["name"])
        else:
            fn = lambda: mod_manager.install_mod(self._category_id, self._mod)
        self._action_worker = _Worker(fn)
        self._action_worker.done.connect(self._on_action_done)
        self._action_worker.start()

    def _on_action_done(self, result):
        self._action_btn.setEnabled(True)
        if isinstance(result, Exception):
            self._status_label.setText("Ошибка, попробуй ещё раз")
            return
        ok, message = result
        self._status_label.setText(message)
        self._refresh_button_state()
        if ok:
            # Was checked-and-installed individually while still queued for
            # the batch button elsewhere - drop it from the queue too.
            self._on_toggle(self._category_id, self._mod, False)


def _os_toggle_button(text, active):
    btn = QPushButton(text)
    btn.setStyleSheet(OS_ACTIVE_STYLE if active else OS_LOCKED_STYLE)
    if active:
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
    else:
        btn.setEnabled(False)
    return btn


class _ImageTile(QFrame):
    """Shared base for the landing page's two image-backed widgets (big
    category tiles, small recently-added cards): a background QLabel
    (category/mod artwork, loaded async), optionally with a bottom
    gradient title strip and/or a small corner count badge stacked on top
    via absolute geometry - fixed-size widgets only, so there's no resize
    handling to do."""
    def __init__(self, width, height, title=None, badge=None):
        super().__init__()
        self.setFixedSize(width, height)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setObjectName("imageTile")
        self.setStyleSheet(
            "QFrame#imageTile { background-color: rgba(255,255,255,8); border-radius: 10px; }"
            "QFrame#imageTile:hover { background-color: rgba(255,255,255,16); }"
        )

        self._bg_label = QLabel(self)
        self._bg_label.setGeometry(0, 0, width, height)
        self._bg_label.setScaledContents(True)

        # Category tile artwork already has its own name baked in by the
        # catalog's own designer (confirmed by eye - "Shaders" etc is
        # literally part of the image) - a title strip here is only used
        # for mods whose preview is a plain gameplay screenshot with no
        # text of its own (recently-added cards).
        if title:
            text_bg = QWidget(self)
            text_bg.setGeometry(0, height - 34, width, 34)
            text_bg.setStyleSheet(
                "background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1, "
                "stop:0 rgba(15,15,20,0), stop:1 rgba(15,15,20,215));"
            )
            text_layout = QVBoxLayout(text_bg)
            text_layout.setContentsMargins(8, 4, 8, 4)
            name_label = QLabel(title)
            name_label.setWordWrap(False)
            name_label.setStyleSheet(
                "color: white; font-family: 'Inter'; font-size: 11px; "
                "font-weight: 700; background: transparent;"
            )
            text_layout.addWidget(name_label)

        if badge:
            badge_label = QLabel(badge, self)
            badge_label.setStyleSheet(
                "background-color: rgba(15,15,20,180); color: #dddddd; "
                "font-family: 'Inter'; font-size: 10px; font-weight: 700; "
                "border-radius: 8px; padding: 2px 8px;"
            )
            badge_label.adjustSize()
            badge_label.move(width - badge_label.width() - 8, 8)

    def _set_preview_pixmap(self, path):
        if not isinstance(path, str) or not os.path.exists(path):
            return
        pixmap = QPixmap(path)
        if pixmap.isNull():
            return
        self._bg_label.setPixmap(pixmap)


class _CategoryTile(_ImageTile):
    def __init__(self, category, count, on_click):
        badge = f"{count} модов" if count != 1 else "1 мод"
        super().__init__(TILE_WIDTH, TILE_HEIGHT, badge=badge)
        self._on_click = on_click
        self._category_id = category["id"]
        self._worker = None
        preview = category.get("preview")
        if preview:
            self._worker = _Worker(lambda: mod_catalog.get_category_preview_path(preview))
            self._worker.done.connect(self._set_preview_pixmap)
            self._worker.start()

    def mousePressEvent(self, event):
        self._on_click(self._category_id)
        super().mousePressEvent(event)


class _RecentCard(_ImageTile):
    def __init__(self, category_id, mod, on_click):
        super().__init__(RECENT_CARD_WIDTH, RECENT_CARD_IMAGE_HEIGHT + 30, title=mod["name"])
        self._on_click = on_click
        self._category_id = category_id
        self._worker = None
        preview = mod.get("preview")
        if preview:
            self._worker = _Worker(lambda: mod_catalog.get_preview_path(category_id, preview))
            self._worker.done.connect(self._set_preview_pixmap)
            self._worker.start()

    def mousePressEvent(self, event):
        self._on_click(self._category_id)
        super().mousePressEvent(event)


def _flow_grid(widgets, columns):
    host = QWidget()
    grid = QGridLayout(host)
    grid.setSpacing(10)
    grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
    for i, w in enumerate(widgets):
        grid.addWidget(w, i // columns, i % columns)
    return host


class _LandingPage(QWidget):
    """"Все категории" landing view: a recently-added carousel up top, a
    grid of big category tiles below - the entry point before drilling
    into any one category's own mod grid."""
    def __init__(self, on_select_category):
        super().__init__()
        self._on_select_category = on_select_category
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        recent = mod_catalog.get_recently_added(RECENT_LIMIT)
        if recent:
            recent_title = QLabel("НЕДАВНО ДОБАВЛЕННЫЕ")
            recent_title.setStyleSheet(
                "color: #999999; font-family: 'Inter'; font-size: 11px; "
                "font-weight: 700; letter-spacing: 1px;"
            )
            layout.addWidget(recent_title)

            carousel_host = QWidget()
            carousel_layout = QHBoxLayout(carousel_host)
            carousel_layout.setContentsMargins(0, 0, 0, 0)
            carousel_layout.setSpacing(10)
            for entry in recent:
                carousel_layout.addWidget(
                    _RecentCard(entry["category"], entry["mod"], self._on_select_category)
                )
            carousel_layout.addStretch()
            carousel_scroll = QScrollArea()
            carousel_scroll.setWidget(carousel_host)
            carousel_scroll.setWidgetResizable(True)
            carousel_scroll.setFrameShape(QFrame.Shape.NoFrame)
            carousel_scroll.setFixedHeight(RECENT_CARD_IMAGE_HEIGHT + 30 + 16)
            carousel_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            carousel_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            carousel_scroll.setStyleSheet(
                "QScrollArea { background: transparent; } "
                "QScrollArea > QWidget > QWidget { background: transparent; }"
            )
            layout.addWidget(carousel_scroll)

        categories_title = QLabel("КАТЕГОРИИ")
        categories_title.setStyleSheet(
            "color: #999999; font-family: 'Inter'; font-size: 11px; "
            "font-weight: 700; letter-spacing: 1px;"
        )
        layout.addWidget(categories_title)

        tiles = [
            _CategoryTile(cat, len(mod_catalog.get_mods(cat["id"])), self._on_select_category)
            for cat in mod_catalog.get_categories()
        ]
        tile_grid = _flow_grid(tiles, TILE_COLUMNS)
        tiles_scroll = QScrollArea()
        tiles_scroll.setWidget(tile_grid)
        tiles_scroll.setWidgetResizable(True)
        tiles_scroll.setFrameShape(QFrame.Shape.NoFrame)
        tiles_scroll.setStyleSheet(
            "QScrollArea { background: transparent; } "
            "QScrollArea > QWidget > QWidget { background: transparent; }"
        )
        layout.addWidget(tiles_scroll, 1)


class _CategoryPage(QWidget):
    """One category's own browsable mod grid - search, multi-select
    checkboxes, batch install. Everything below the sidebar/landing page
    that used to be _ModsPage's own body before the redesign."""
    def __init__(self, get_selected, on_toggle, on_batch_install):
        super().__init__()
        self._get_selected = get_selected
        self._on_toggle = on_toggle
        self._on_batch_install = on_batch_install
        self._current_category = None
        self._all_mods = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self._title = QLabel("")
        self._title.setStyleSheet(
            "color: white; font-family: 'Inter'; font-size: 18px; font-weight: 800;"
        )
        layout.addWidget(self._title)

        search_bar = QHBoxLayout()
        self._search = QLineEdit()
        self._search.setPlaceholderText("Поиск по названию...")
        self._search.setStyleSheet(
            "QLineEdit { background-color: rgba(255,255,255,10); color: white; "
            "border: 1px solid rgba(255,255,255,30); border-radius: 4px; padding: 6px 10px; "
            "font-family: 'Inter'; font-size: 12px; }"
        )
        self._search.textChanged.connect(self._rebuild_grid)
        search_bar.addWidget(self._search, 1)

        self._clear_selection_btn = QPushButton("Очистить выбор")
        self._clear_selection_btn.setStyleSheet(SECONDARY_BUTTON_STYLE)
        self._clear_selection_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._clear_selection_btn.clicked.connect(lambda: self._on_batch_install("clear"))
        search_bar.addWidget(self._clear_selection_btn)

        self._batch_btn = QPushButton()
        self._batch_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._batch_btn.clicked.connect(lambda: self._on_batch_install("install"))
        search_bar.addWidget(self._batch_btn)
        layout.addLayout(search_bar)

        self._grid_host = QWidget()
        self._grid = QGridLayout(self._grid_host)
        self._grid.setSpacing(10)
        self._grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        scroll = QScrollArea()
        scroll.setWidget(self._grid_host)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet(
            "QScrollArea { background: transparent; } "
            "QScrollArea > QWidget > QWidget { background: transparent; }"
        )
        layout.addWidget(scroll, 1)

        self._status_label = QLabel("")
        self._status_label.setStyleSheet("color: #888888; font-family: 'Inter'; font-size: 11px;")
        layout.addWidget(self._status_label)

        self.refresh_batch_button()

    def show_category(self, category):
        self._current_category = category["id"]
        self._title.setText(f"{category['emoji']}  {category['name']}")
        self._all_mods = mod_catalog.get_mods(category["id"])
        self._search.blockSignals(True)
        self._search.clear()
        self._search.blockSignals(False)
        self._rebuild_grid()

    def refresh_batch_button(self):
        count = len(self._get_selected())
        self._batch_btn.setText(f"Установить выбранное ({count})" if count else "Установить выбранное")
        self._batch_btn.setEnabled(count > 0)
        self._batch_btn.setStyleSheet(PRIMARY_BUTTON_STYLE)
        self._clear_selection_btn.setEnabled(count > 0)

    def set_status(self, text):
        self._status_label.setText(text)

    def _rebuild_grid(self):
        while self._grid.count():
            item = self._grid.takeAt(0)
            widget = item.widget()
            if widget:
                widget.hide()
                widget.deleteLater()

        query = self._search.text().strip().lower()
        filtered = (
            [m for m in self._all_mods if query in m["name"].lower()]
            if query else self._all_mods
        )

        selected = self._get_selected()
        shown = filtered[:MODS_PER_PAGE]
        for i, mod in enumerate(shown):
            key = (self._current_category, mod["name"])
            card = _ModCard(
                self._current_category, mod,
                checked=key in selected,
                on_toggle=self._on_toggle,
            )
            self._grid.addWidget(card, i // GRID_COLUMNS, i % GRID_COLUMNS)

        if not filtered:
            self._status_label.setText("Ничего не найдено")
        elif len(filtered) > MODS_PER_PAGE:
            self._status_label.setText(
                f"Показаны первые {MODS_PER_PAGE} из {len(filtered)} — уточни поиск"
            )
        else:
            self._status_label.setText(f"{len(filtered)} модов")


def _sidebar_row_widget(text, count=None, bold=False):
    row = QWidget()
    row.setStyleSheet("background: transparent;")
    row_layout = QHBoxLayout(row)
    row_layout.setContentsMargins(6, 3, 6, 3)
    label = QLabel(text)
    weight = 700 if bold else 500
    label.setStyleSheet(
        f"color: {'white' if bold else '#dddddd'}; font-family: 'Inter'; "
        f"font-size: 12px; font-weight: {weight}; background: transparent;"
    )
    row_layout.addWidget(label, 1)
    if count is not None:
        count_label = QLabel(str(count))
        count_label.setStyleSheet(
            "color: #888888; font-family: 'Inter'; font-size: 11px; background: transparent;"
        )
        row_layout.addWidget(count_label, 0, Qt.AlignmentFlag.AlignRight)
    return row


def _sidebar_header_widget(text):
    label = QLabel(text)
    label.setContentsMargins(6, 10, 6, 2)
    label.setStyleSheet(
        "color: #777777; font-family: 'Inter'; font-size: 10px; "
        "font-weight: 700; letter-spacing: 1px; background: transparent;"
    )
    return label


class _ModsPage(QWidget):
    def __init__(self):
        super().__init__()
        # {(category_id, mod_name): mod} - the batch-install queue. Kept
        # here, not on individual cards, so it survives switching category
        # (the grid, and every _ModCard in it, gets thrown away and rebuilt
        # on every category/search change).
        self._selected = {}
        self._batch_worker = None
        self._categories = mod_catalog.get_categories()
        self._counts = {c["id"]: len(mod_catalog.get_mods(c["id"])) for c in self._categories}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        header = QVBoxLayout()
        header.setSpacing(2)
        title = QLabel("МОДЫ ДЛЯ DOTA 2")
        title.setStyleSheet(
            "color: white; font-family: 'Inter'; font-size: 20px; font-weight: 800;"
        )
        header.addWidget(title)
        total = sum(self._counts.values())
        subtitle = QLabel(
            f"{total} модов в {len(self._categories)} категориях · "
            "открытый каталог Dota2PornFx (github.com/h6rd)"
        )
        subtitle.setStyleSheet("color: #999999; font-family: 'Inter'; font-size: 11px;")
        header.addWidget(subtitle)
        layout.addLayout(header)

        os_bar = QHBoxLayout()
        os_label = QLabel("Платформа:")
        os_label.setStyleSheet("color: #aaaaaa; font-family: 'Inter'; font-size: 11px;")
        os_bar.addWidget(os_label)
        os_bar.addWidget(_os_toggle_button("🐧 Linux", active=True))
        windows_btn = _os_toggle_button("🔒 Windows", active=False)
        windows_btn.setToolTip("Скоро — заработает после установки Windows на отдельный диск")
        os_bar.addWidget(windows_btn)
        os_bar.addStretch()
        layout.addLayout(os_bar)

        layout.addWidget(_ToolsPanel())

        body = QHBoxLayout()
        body.setSpacing(12)

        self._category_list = QListWidget()
        self._category_list.setFixedWidth(210)
        self._category_list.setStyleSheet(
            "QListWidget { background-color: rgba(255,255,255,10); color: white; "
            "font-family: 'Inter'; font-size: 12px; border: none; border-radius: 6px; }"
            "QListWidget::item { border-radius: 4px; }"
            "QListWidget::item:selected { background-color: rgba(255,255,255,30); }"
        )
        self._build_sidebar()
        self._category_list.currentRowChanged.connect(self._on_sidebar_row_changed)
        body.addWidget(self._category_list)

        self._stack = QStackedWidget()
        self._landing_page = _LandingPage(on_select_category=self._select_category)
        self._category_page = _CategoryPage(
            get_selected=lambda: self._selected,
            on_toggle=self._on_card_toggle,
            on_batch_install=self._on_category_page_action,
        )
        self._stack.addWidget(self._landing_page)
        self._stack.addWidget(self._category_page)
        body.addWidget(self._stack, 1)

        layout.addLayout(body, 1)

        footer = QFrame()
        footer.setObjectName("modsFooter")
        footer.setStyleSheet(
            "QFrame#modsFooter { background-color: rgba(255,255,255,6); border-radius: 12px; }"
        )
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(14, 8, 14, 8)

        self._footer_dot = QLabel("")
        self._footer_dot.setStyleSheet("background: transparent;")
        footer_layout.addWidget(self._footer_dot)
        self._footer_status_label = QLabel("")
        self._footer_status_label.setStyleSheet(
            "color: #cccccc; font-family: 'Inter'; font-size: 11px; background: transparent;"
        )
        footer_layout.addWidget(self._footer_status_label)
        footer_layout.addStretch()

        # Editable, not just a static "-language russian" label - lets the
        # user point installs at whatever OFFICIAL Dota language slot they
        # want (e.g. "english"). Valve now blocks arbitrary custom slots
        # ("123", "minify", etc) - only real language folders still work,
        # per the catalog's own site notice (2026-08-08) - hence the
        # default is "russian", not a made-up custom name, and non-
        # official values get flagged, not silently accepted.
        lang_label = QLabel("-language:")
        lang_label.setStyleSheet("color: #999999; font-family: 'Inter'; font-size: 11px; background: transparent;")
        footer_layout.addWidget(lang_label)
        self._language_field = QLineEdit(mod_manager.get_language())
        self._language_field.setFixedWidth(90)
        self._language_field.setToolTip(
            "Valve заблокировала кастомные -language (123, minify и т.п.) — работают только "
            "официальные языки Dota (russian, english, ...). Даже для английской Dota "
            "рекомендуют russian — эта папка точно поддерживается."
        )
        footer_layout.addWidget(self._language_field)
        save_lang_btn = QPushButton("Сохранить")
        save_lang_btn.setStyleSheet(SECONDARY_BUTTON_STYLE)
        save_lang_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        save_lang_btn.clicked.connect(self._on_save_language)
        footer_layout.addWidget(save_lang_btn)
        copy_btn = QPushButton("Скопировать")
        copy_btn.setStyleSheet(SECONDARY_BUTTON_STYLE)
        copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        copy_btn.clicked.connect(self._copy_launch_option)
        footer_layout.addWidget(copy_btn)

        open_folder_btn = QPushButton("Открыть папку модов")
        open_folder_btn.setStyleSheet(SECONDARY_BUTTON_STYLE)
        open_folder_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        open_folder_btn.clicked.connect(self._open_mods_folder)
        footer_layout.addWidget(open_folder_btn)

        # Same right-edge, highest-visual-weight placement as the
        # reference Mod Manager's own "▶ Играть" button - launches Dota
        # straight through Steam's own protocol handler (steamapps' own
        # launch machinery, incl. whatever -language/launch options are
        # already configured in Steam - this button doesn't duplicate or
        # bypass that).
        play_btn = QPushButton("▶ Играть")
        play_btn.setStyleSheet(PRIMARY_BUTTON_STYLE)
        play_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        play_btn.clicked.connect(self._launch_dota)
        footer_layout.addWidget(play_btn)
        layout.addWidget(footer)

        self._refresh_footer()

    def _add_sidebar_item(self, widget, category_id=..., selectable=True):
        item = QListWidgetItem()
        if not selectable:
            item.setFlags(Qt.ItemFlag.NoItemFlags)
        elif category_id is not ...:
            item.setData(Qt.ItemDataRole.UserRole, category_id)
        self._category_list.addItem(item)
        self._category_list.setItemWidget(item, widget)
        # setItemWidget alone leaves the row's height at QListWidget's
        # default - without an explicit sizeHint here, taller custom
        # widgets (or, as first found here, the group headers' own top
        # margin) get vertically clipped instead of the row growing to fit.
        item.setSizeHint(widget.sizeHint())

    def _build_sidebar(self):
        self._add_sidebar_item(
            _sidebar_row_widget("🗂 Все категории", sum(self._counts.values()), bold=True),
            category_id=None,
        )

        grouped = {}
        for cat in self._categories:
            grouped.setdefault(_CATEGORY_GROUPS.get(cat["id"], _FALLBACK_GROUP), []).append(cat)

        for group in _GROUP_ORDER:
            cats = grouped.get(group)
            if not cats:
                continue
            self._add_sidebar_item(_sidebar_header_widget(group), selectable=False)
            for cat in cats:
                self._add_sidebar_item(
                    _sidebar_row_widget(f"{cat['emoji']}  {cat['name']}", self._counts[cat["id"]]),
                    category_id=cat["id"],
                )

        self._category_list.setCurrentRow(0)

    def _on_sidebar_row_changed(self, row):
        item = self._category_list.item(row)
        if item is None:
            return
        category_id = item.data(Qt.ItemDataRole.UserRole)
        if category_id is None:
            self._stack.setCurrentWidget(self._landing_page)
        else:
            self._select_category(category_id)

    def _select_category(self, category_id):
        category = next((c for c in self._categories if c["id"] == category_id), None)
        if category is None:
            return
        # Programmatic navigation from a tile/carousel card - keep the
        # sidebar's own selection in sync so it doesn't silently disagree
        # with what's actually shown.
        for row in range(self._category_list.count()):
            if self._category_list.item(row).data(Qt.ItemDataRole.UserRole) == category_id:
                self._category_list.blockSignals(True)
                self._category_list.setCurrentRow(row)
                self._category_list.blockSignals(False)
                break
        self._category_page.show_category(category)
        self._stack.setCurrentWidget(self._category_page)

    def _refresh_footer(self):
        found = mod_manager.dota_found()
        self._footer_dot.setText("🟢" if found else "🔴")
        mods_dir_name = os.path.basename(mod_manager.get_mods_dir())
        minify_language = mod_language_settings.detect_minify_language()
        synced_with_minify = minify_language is not None and minify_language == mod_manager.get_language()
        status = f"Dota 2 найдена · моды ставятся в {mods_dir_name}" if found \
            else f"Dota 2 не найдена ({mod_manager.DOTA_GAME_DIR})"
        if synced_with_minify:
            status += " · синхронизировано с Minify"
        elif minify_language:
            status += f" · ⚠ у Minify другой язык ({minify_language})"
        self._footer_status_label.setText(status)
        official = mod_language_settings.is_official(mod_manager.get_language())
        self._language_field.setStyleSheet(
            LANGUAGE_FIELD_STYLE_OK if official else LANGUAGE_FIELD_STYLE_WARN
        )

    def _copy_launch_option(self):
        QApplication.clipboard().setText(mod_manager.get_launch_option())

    def _open_mods_folder(self):
        mods_dir = mod_manager.get_mods_dir()
        os.makedirs(mods_dir, exist_ok=True)
        subprocess.Popen(["xdg-open", mods_dir])

    def _launch_dota(self):
        # steam://rungameid/<appid> is Steam's own documented protocol
        # handler - goes through Steam's normal launch path (whatever
        # launch options/compat tool are already configured there), not a
        # separate/duplicate way of starting the game.
        subprocess.Popen(["xdg-open", "steam://rungameid/570"])

    def _on_save_language(self):
        new_language = self._language_field.text().strip()
        if new_language == mod_manager.get_language():
            return
        if not mod_language_settings.is_valid(new_language):
            self._footer_status_label.setText(
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
        self._footer_status_label.setText(message)
        if ok:
            self._refresh_footer()
            self._category_page._rebuild_grid()

    def _on_card_toggle(self, category_id, mod, checked):
        key = (category_id, mod["name"])
        if checked:
            self._selected[key] = mod
        else:
            self._selected.pop(key, None)
        self._category_page.refresh_batch_button()

    def _on_category_page_action(self, action):
        if action == "clear":
            self._selected = {}
            self._category_page.refresh_batch_button()
            self._category_page._rebuild_grid()
        elif action == "install":
            self._start_batch_install()

    def _start_batch_install(self):
        jobs = list(self._selected.items())
        if not jobs:
            return
        self._category_page._batch_btn.setEnabled(False)
        self._category_page._clear_selection_btn.setEnabled(False)
        self._batch_worker = _BatchInstallWorker([(cat, mod) for (cat, _name), mod in jobs])
        self._batch_worker.progress.connect(self._on_batch_progress)
        self._batch_worker.finished_all.connect(self._on_batch_finished)
        self._batch_worker.start()

    def _on_batch_progress(self, done, total, mod_name, ok):
        verdict = "OK" if ok else "ошибка"
        self._category_page.set_status(f"Установка {done}/{total}: {mod_name} — {verdict}")

    def _on_batch_finished(self):
        self._selected = {}
        self._category_page.refresh_batch_button()
        self._category_page._rebuild_grid()
