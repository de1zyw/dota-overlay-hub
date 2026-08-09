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

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QCheckBox, QFrame, QGridLayout, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QPushButton,
    QScrollArea, QStackedWidget, QVBoxLayout, QWidget,
)

import category_icons
import mod_catalog
import mod_language_settings
import mod_manager
from cart_dialog import CartDialog
from tools_panel import _ToolsPanel
from ui_common import PRIMARY_BUTTON_STYLE, SCROLLBAR_STYLE, SECONDARY_BUTTON_STYLE
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
# The MINIMUM a card is allowed to shrink to when deciding how many columns
# fit - actual on-screen card width is then stretched up from here to fill
# the row exactly (see _CategoryPage._compute_columns_and_width), so there's
# never a leftover strip of dead space next to the last column.
CARD_WIDTH = 230
PREVIEW_HEIGHT = 155
_CARD_ASPECT = PREVIEW_HEIGHT / CARD_WIDTH  # preserved as cards stretch
GRID_COLUMNS = 3  # fallback only - _CategoryPage recomputes this from actual width

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


class _ModCard(QFrame):
    def __init__(self, category_id, mod, checked, on_toggle, width=CARD_WIDTH):
        super().__init__()
        self._category_id = category_id
        self._mod = mod
        self._on_toggle = on_toggle
        self._preview_worker = None
        self._action_worker = None
        self._original_pixmap = None  # full-res, kept around so re-stretching (set_width) never re-blurs a scale-of-a-scale

        self.setObjectName("modCard")
        self.setStyleSheet(
            "QFrame#modCard { background-color: rgba(255,255,255,10); border-radius: 12px; }"
        )
        self.setFixedWidth(width)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # cursors/fonts overwrite a single shared destination (one active
        # set at a time - see mod_manager.install_loose_mod) - queueing
        # several for the batch button would just waste downloads on
        # every one but the last processed, so there's no checkbox to
        # queue them with at all here.
        self._exclusive = mod_manager.is_loose_file_category(category_id)

        top_row = QHBoxLayout()
        top_row.setSpacing(4)
        if self._exclusive:
            self._checkbox = None
        else:
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

        if self._exclusive:
            exclusive_hint = QLabel("⚡ заменяет текущий")
            exclusive_hint.setStyleSheet(
                "color: #b388ff; font-family: 'Inter'; font-size: 9px; background: transparent;"
            )
            layout.addWidget(exclusive_hint)

        self._preview_label = QLabel()
        self._preview_label.setFixedSize(width - 16, round((width - 16) * _CARD_ASPECT))
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
        if self._checkbox is None:
            return
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
        self._original_pixmap = pixmap
        self._apply_preview_scale()

    def _apply_preview_scale(self):
        if self._original_pixmap is None:
            return
        scaled = self._original_pixmap.scaled(
            self._preview_label.width(), self._preview_label.height(),
            Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation,
        )
        self._preview_label.setPixmap(scaled)

    def set_width(self, width):
        """Resizes an already-built card in place (window-resize reflow -
        see _CategoryPage._relayout_grid) - re-scales from the original,
        full-res pixmap rather than the previous (already-downscaled) one,
        so stretching a card back up after shrinking it never looks
        blurrier than a freshly loaded preview would."""
        if width == self.width():
            return
        self.setFixedWidth(width)
        self._preview_label.setFixedSize(width - 16, round((width - 16) * _CARD_ASPECT))
        self._apply_preview_scale()

    def _on_action_clicked(self):
        self._action_btn.setEnabled(False)
        installed = mod_manager.is_installed(self._category_id, self._mod["name"])
        loose = mod_manager.is_loose_file_category(self._category_id)
        if installed:
            uninstaller = mod_manager.uninstall_loose_mod if loose else mod_manager.uninstall_mod
            fn = lambda: uninstaller(self._category_id, self._mod["name"])
        else:
            installer = mod_manager.install_loose_mod if loose else mod_manager.install_mod
            fn = lambda: installer(self._category_id, self._mod)
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
        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.timeout.connect(self._on_resize_settled)
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
                + SCROLLBAR_STYLE
            )
            layout.addWidget(carousel_scroll)

        categories_title = QLabel("КАТЕГОРИИ")
        categories_title.setStyleSheet(
            "color: #999999; font-family: 'Inter'; font-size: 11px; "
            "font-weight: 700; letter-spacing: 1px;"
        )
        layout.addWidget(categories_title)

        self._tiles = [
            _CategoryTile(cat, len(mod_catalog.get_mods(cat["id"])), self._on_select_category)
            for cat in mod_catalog.get_categories()
        ]
        self._tile_host = QWidget()
        self._tile_grid = QGridLayout(self._tile_host)
        self._tile_grid.setSpacing(10)
        self._tile_grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self._tile_columns = TILE_COLUMNS
        self._layout_tiles()
        self._tiles_scroll = QScrollArea()
        self._tiles_scroll.setWidget(self._tile_host)
        self._tiles_scroll.setWidgetResizable(True)
        self._tiles_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._tiles_scroll.setStyleSheet(
            "QScrollArea { background: transparent; } "
            "QScrollArea > QWidget > QWidget { background: transparent; }"
            + SCROLLBAR_STYLE
        )
        layout.addWidget(self._tiles_scroll, 1)

    def _layout_tiles(self):
        while self._tile_grid.count():
            self._tile_grid.takeAt(0)
        for i, tile in enumerate(self._tiles):
            self._tile_grid.addWidget(tile, i // self._tile_columns, i % self._tile_columns)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Debounced - a live window drag fires resizeEvent continuously,
        # not once at the end. Recomputing on every single one of those
        # (even just a cheap re-layout) is wasted work piling up mid-drag.
        self._resize_timer.start(150)

    def _on_resize_settled(self):
        spacing = self._tile_grid.spacing() or 10
        available = max(self._tiles_scroll.viewport().width() - 4, TILE_WIDTH)
        columns = max(1, (available + spacing) // (TILE_WIDTH + spacing))
        if columns != self._tile_columns:
            self._tile_columns = columns
            self._layout_tiles()


class _CategoryPage(QWidget):
    """One category's own browsable mod grid - search, multi-select
    checkboxes, batch install. Everything below the sidebar/landing page
    that used to be _ModsPage's own body before the redesign."""
    def __init__(self, get_selected, on_toggle):
        super().__init__()
        self._get_selected = get_selected
        self._on_toggle = on_toggle
        self._current_category = None
        self._all_mods = []
        self._grid_columns = GRID_COLUMNS
        self._card_width = CARD_WIDTH
        self._cards = []
        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.timeout.connect(self._on_resize_settled)

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
        layout.addLayout(search_bar)

        self._grid_host = QWidget()
        self._grid = QGridLayout(self._grid_host)
        self._grid.setSpacing(10)
        self._grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self._scroll = QScrollArea()
        self._scroll.setWidget(self._grid_host)
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setStyleSheet(
            "QScrollArea { background: transparent; } "
            "QScrollArea > QWidget > QWidget { background: transparent; }"
            + SCROLLBAR_STYLE
        )
        layout.addWidget(self._scroll, 1)

        self._status_label = QLabel("")
        self._status_label.setStyleSheet("color: #888888; font-family: 'Inter'; font-size: 11px;")
        layout.addWidget(self._status_label)

    def show_category(self, category):
        self._current_category = category["id"]
        self._title.setTextFormat(Qt.TextFormat.PlainText)
        emoji = category_icons.get_emoji(category["id"], category["emoji"])
        self._title.setText(f"{emoji}  {category['name']}")
        if category_icons.has_real_icon(category["id"]):
            cid, name = category["id"], category["name"]
            worker = _Worker(lambda: category_icons.get_icon_path(cid))
            worker.done.connect(lambda path: self._on_title_icon_loaded(cid, name, path))
            worker.start()
            self._title_icon_worker = worker
        self._all_mods = mod_catalog.get_mods(category["id"])
        self._search.blockSignals(True)
        self._search.clear()
        self._search.blockSignals(False)
        self._grid_columns, self._card_width = self._compute_columns_and_width()
        self._rebuild_grid()

    def _on_title_icon_loaded(self, category_id, name, path):
        # The user may have already clicked to a different category before
        # this fetch (cache miss -> real network round trip) came back -
        # only apply it if the title is still showing the category it was
        # fetched for.
        if category_id != self._current_category or not isinstance(path, str) or not os.path.exists(path):
            return
        self._title.setTextFormat(Qt.TextFormat.RichText)
        self._title.setText(f'<img src="file://{path}" width="22" height="22"> &nbsp;{name}')

    def set_status(self, text):
        self._status_label.setText(text)

    def _compute_columns_and_width(self):
        spacing = self._grid.spacing() or 10
        # The scroll area's VIEWPORT width (not self.width(), which
        # includes margins this widget doesn't actually give the grid) -
        # a small -4 fudge for the grid's own inner margins.
        available = max(self._scroll.viewport().width() - 4, CARD_WIDTH)
        columns = max(1, (available + spacing) // (CARD_WIDTH + spacing))
        # CARD_WIDTH is only the MINIMUM used to decide how many columns
        # fit - stretch each card up to actually fill the row exactly, so
        # there's never a leftover strip of dead space next to the last
        # column (this is what CARD_WIDTH alone used to leave behind).
        width = int((available - (columns - 1) * spacing) // columns)
        return columns, max(width, CARD_WIDTH)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Debounced, and settling only triggers a cheap re-layout (see
        # _on_resize_settled) - NOT a full rebuild. A live window drag
        # fires resizeEvent continuously; the original version rebuilt
        # (destroyed + recreated, including re-spinning a fresh preview-
        # download QThread per card) all 60 cards on every single one of
        # those, which is exactly what made resizing feel frozen for
        # seconds - real bug, not a Python-is-slow problem.
        self._resize_timer.start(150)

    def _on_resize_settled(self):
        columns, width = self._compute_columns_and_width()
        if columns != self._grid_columns or width != self._card_width:
            self._grid_columns = columns
            self._card_width = width
            self._relayout_grid()

    def _relayout_grid(self):
        """Repositions the ALREADY-BUILT self._cards into the grid at the
        current column count/width - no widget destruction, no re-
        fetching previews (each card re-scales from its own cached
        original pixmap - see _ModCard.set_width). Safe to call as often
        as needed (window resize)."""
        while self._grid.count():
            self._grid.takeAt(0)
        for i, card in enumerate(self._cards):
            card.set_width(self._card_width)
            self._grid.addWidget(card, i // self._grid_columns, i % self._grid_columns)

    def _rebuild_grid(self):
        """Full rebuild: destroys and recreates every card. Only for when
        the actual mod list changed (new category, new search text) - a
        pure re-layout (window resize) must go through _relayout_grid()
        instead, see the comment there for why."""
        while self._grid.count():
            item = self._grid.takeAt(0)
            widget = item.widget()
            if widget:
                widget.hide()
                widget.deleteLater()
        self._cards = []

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
                width=self._card_width,
            )
            self._cards.append(card)
            self._grid.addWidget(card, i // self._grid_columns, i % self._grid_columns)

        if not filtered:
            self._status_label.setText("Ничего не найдено")
        elif len(filtered) > MODS_PER_PAGE:
            self._status_label.setText(
                f"Показаны первые {MODS_PER_PAGE} из {len(filtered)} — уточни поиск"
            )
        else:
            self._status_label.setText(f"{len(filtered)} модов")


def _apply_icon_pixmap(label, path):
    if not isinstance(path, str) or not os.path.exists(path):
        return
    pixmap = QPixmap(path).scaled(
        16, 16, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation,
    )
    label.setPixmap(pixmap)
    label.setText("")


def _sidebar_row_widget(text, count=None, bold=False, category_id=None, emoji=""):
    row = QWidget()
    row.setStyleSheet("background: transparent;")
    row_layout = QHBoxLayout(row)
    row_layout.setContentsMargins(6, 3, 6, 3)
    row_layout.setSpacing(6)

    if category_id is not None:
        icon_label = QLabel(emoji)
        icon_label.setFixedWidth(18)
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_label.setStyleSheet("background: transparent; font-size: 13px;")
        row_layout.addWidget(icon_label)
        if category_icons.has_real_icon(category_id):
            # Kept alive as an attribute on the row itself - the row widget
            # lives for as long as it's in the sidebar QListWidget, same
            # lifetime as the icon it's fetching.
            worker = _Worker(lambda cid=category_id: category_icons.get_icon_path(cid))
            worker.done.connect(lambda path, lbl=icon_label: _apply_icon_pixmap(lbl, path))
            worker.start()
            row._icon_worker = worker

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
            + SCROLLBAR_STYLE
        )
        self._build_sidebar()
        self._category_list.currentRowChanged.connect(self._on_sidebar_row_changed)
        body.addWidget(self._category_list)

        self._stack = QStackedWidget()
        self._landing_page = _LandingPage(on_select_category=self._select_category)
        self._category_page = _CategoryPage(
            get_selected=lambda: self._selected,
            on_toggle=self._on_card_toggle,
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

        open_folder_btn = QPushButton("Открыть папку модов")
        open_folder_btn.setStyleSheet(SECONDARY_BUTTON_STYLE)
        open_folder_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        open_folder_btn.clicked.connect(self._open_mods_folder)
        footer_layout.addWidget(open_folder_btn)

        self._clear_selection_btn = QPushButton("Очистить выбор")
        self._clear_selection_btn.setStyleSheet(SECONDARY_BUTTON_STYLE)
        self._clear_selection_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._clear_selection_btn.clicked.connect(lambda: self._on_category_page_action("clear"))
        footer_layout.addWidget(self._clear_selection_btn)

        self._batch_btn = QPushButton()
        self._batch_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._batch_btn.clicked.connect(lambda: self._on_category_page_action("install"))
        footer_layout.addWidget(self._batch_btn)
        layout.addWidget(footer)

        self._refresh_footer()
        self._refresh_cart_buttons()

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
                    _sidebar_row_widget(
                        cat["name"], self._counts[cat["id"]],
                        category_id=cat["id"], emoji=category_icons.get_emoji(cat["id"], cat["emoji"]),
                    ),
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

    def _open_mods_folder(self):
        mods_dir = mod_manager.get_mods_dir()
        os.makedirs(mods_dir, exist_ok=True)
        subprocess.Popen(["xdg-open", mods_dir])

    def _refresh_cart_buttons(self):
        count = len(self._selected)
        # Always enabled, even at 0 - the cart dialog is also how saved
        # presets get loaded (mod_presets.py), not just how a live
        # selection gets installed, so there's a reason to open it empty.
        self._batch_btn.setText(f"Корзина ({count})" if count else "Корзина")
        self._batch_btn.setStyleSheet(PRIMARY_BUTTON_STYLE)
        self._clear_selection_btn.setEnabled(count > 0)

    def _on_card_toggle(self, category_id, mod, checked):
        key = (category_id, mod["name"])
        if checked:
            self._selected[key] = mod
        else:
            self._selected.pop(key, None)
        self._refresh_cart_buttons()

    def _on_category_page_action(self, action):
        if action == "clear":
            self._selected.clear()
            self._refresh_cart_buttons()
            self._category_page._rebuild_grid()
        elif action == "install":
            self._open_cart()

    def _open_cart(self):
        # Same dict OBJECT as self._selected, not a copy - the dialog
        # mutates it in place (item removal, clearing after install), so
        # closing it needs no separate sync step; _on_cart_change just
        # refreshes what's already visible behind it.
        dialog = CartDialog(self, self._selected, on_change=self._on_cart_change)
        dialog.exec()
        self._on_cart_change()

    def _on_cart_change(self):
        self._refresh_cart_buttons()
        self._category_page._rebuild_grid()
