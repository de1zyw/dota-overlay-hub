"""МОДЫ tab: browses the open Dota2PornFx mod catalog (mod_catalog.py) and
installs/removes cosmetic mods via mod_manager.py. Preview downloads and
install/uninstall both hit the network - each runs on its own throwaway
QThread so neither ever blocks the Qt event loop."""
import os

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QApplication, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QPushButton, QScrollArea, QVBoxLayout,
    QWidget,
)

import mod_catalog
import mod_manager

# Duplicated from launcher.py rather than imported - launcher.py imports
# this module to build its МОДЫ tab, so importing back from here would be
# a circular import. Same visual language, just two small style strings.
SECONDARY_BUTTON_STYLE = """
QPushButton {
    background-color: rgba(255, 255, 255, 15);
    color: #dddddd;
    border: 1px solid rgba(255, 255, 255, 30);
    border-radius: 6px;
    padding: 6px 12px;
    font-family: sans-serif;
    font-size: 11px;
    font-weight: 600;
}
QPushButton:hover {
    background-color: rgba(255, 255, 255, 25);
    border: 1px solid rgba(255, 255, 255, 50);
}
QPushButton:disabled {
    background-color: rgba(255, 255, 255, 8);
    color: #666666;
}
"""

PRIMARY_BUTTON_STYLE = """
QPushButton {
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #FF9CE3, stop:0.5 #B388FF, stop:1 #7DD3FC);
    color: #14141a;
    border: none;
    border-radius: 6px;
    padding: 6px 12px;
    font-family: sans-serif;
    font-size: 11px;
    font-weight: 700;
}
QPushButton:hover {
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #ffb3ea, stop:0.5 #c39dff, stop:1 #93ddff);
}
QPushButton:disabled {
    background-color: rgba(255, 255, 255, 12);
    color: #666666;
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


class _Worker(QThread):
    """Runs one blocking callable off the Qt main thread; emits its return
    value (or the caught exception, if it raised) on `done`."""
    done = pyqtSignal(object)

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self._fn = fn

    def run(self):
        try:
            result = self._fn()
        except Exception as exc:  # noqa: BLE001 - surfaced to the UI, not swallowed
            result = exc
        self.done.emit(result)


class _ModCard(QFrame):
    def __init__(self, category_id, mod):
        super().__init__()
        self._category_id = category_id
        self._mod = mod
        self._preview_worker = None
        self._action_worker = None

        self.setObjectName("modCard")
        self.setStyleSheet(
            "QFrame#modCard { background-color: rgba(255,255,255,10); border-radius: 8px; }"
        )
        self.setFixedWidth(CARD_WIDTH)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        self._preview_label = QLabel()
        self._preview_label.setFixedSize(CARD_WIDTH - 16, PREVIEW_HEIGHT)
        self._preview_label.setStyleSheet(
            "background-color: rgba(0,0,0,60); border-radius: 4px;"
        )
        self._preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._preview_label)

        name = QLabel(mod["name"])
        name.setWordWrap(True)
        name.setFixedHeight(32)
        name.setStyleSheet(
            "color: white; font-family: sans-serif; font-size: 11px; "
            "font-weight: 600; background: transparent;"
        )
        layout.addWidget(name)

        self._action_btn = QPushButton()
        self._action_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._action_btn.clicked.connect(self._on_action_clicked)
        layout.addWidget(self._action_btn)

        self._status_label = QLabel("")
        self._status_label.setWordWrap(True)
        self._status_label.setStyleSheet(
            "color: #999999; font-family: sans-serif; font-size: 10px; background: transparent;"
        )
        layout.addWidget(self._status_label)

        self._refresh_button_state()
        self._load_preview()

    def _refresh_button_state(self):
        installed = mod_manager.is_installed(self._category_id, self._mod["name"])
        self._action_btn.setText("Удалить" if installed else "Установить")
        self._action_btn.setStyleSheet(SECONDARY_BUTTON_STYLE if installed else PRIMARY_BUTTON_STYLE)

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


class _ModsPage(QWidget):
    def __init__(self):
        super().__init__()
        self._current_category = None
        self._all_mods = []

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        self._category_list = QListWidget()
        self._category_list.setFixedWidth(200)
        self._category_list.setStyleSheet(
            "QListWidget { background-color: rgba(255,255,255,10); color: white; "
            "font-family: sans-serif; font-size: 12px; border: none; border-radius: 6px; }"
            "QListWidget::item { padding: 6px; }"
            "QListWidget::item:selected { background-color: rgba(255,255,255,30); }"
        )
        for cat in mod_catalog.get_categories():
            item = QListWidgetItem(f"{cat['emoji']}  {cat['name']}")
            item.setData(Qt.ItemDataRole.UserRole, cat["id"])
            self._category_list.addItem(item)
        self._category_list.currentRowChanged.connect(self._on_category_changed)
        layout.addWidget(self._category_list)

        right = QVBoxLayout()
        right.setSpacing(8)

        hint_bar = QHBoxLayout()
        hint = QLabel(
            "Моды кладутся в отдельную папку Dota и требуют параметр запуска "
            f"«{mod_manager.LAUNCH_OPTION}» — Steam → Dota 2 → Свойства → Параметры запуска "
            "(добавляется один раз)."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #aaaaaa; font-family: sans-serif; font-size: 11px;")
        hint_bar.addWidget(hint, 1)
        copy_btn = QPushButton("Скопировать")
        copy_btn.setStyleSheet(SECONDARY_BUTTON_STYLE)
        copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        copy_btn.clicked.connect(self._copy_launch_option)
        hint_bar.addWidget(copy_btn)
        right.addLayout(hint_bar)

        if not mod_manager.dota_found():
            warn = QLabel(
                f"Папка Dota 2 не найдена ({mod_manager.DOTA_GAME_DIR}) — установка модов "
                "отключена, пока Dota не будет найдена."
            )
            warn.setWordWrap(True)
            warn.setStyleSheet("color: #e2574c; font-family: sans-serif; font-size: 11px;")
            right.addWidget(warn)

        self._search = QLineEdit()
        self._search.setPlaceholderText("Поиск по названию...")
        self._search.setStyleSheet(
            "QLineEdit { background-color: rgba(255,255,255,10); color: white; "
            "border: 1px solid rgba(255,255,255,30); border-radius: 4px; padding: 6px 10px; "
            "font-family: sans-serif; font-size: 12px; }"
        )
        self._search.textChanged.connect(self._on_search_changed)
        right.addWidget(self._search)

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
        right.addWidget(scroll, 1)

        self._status_label = QLabel("")
        self._status_label.setStyleSheet("color: #888888; font-family: sans-serif; font-size: 11px;")
        right.addWidget(self._status_label)

        layout.addLayout(right, 1)

        if self._category_list.count():
            self._category_list.setCurrentRow(0)

    def _copy_launch_option(self):
        QApplication.clipboard().setText(mod_manager.LAUNCH_OPTION)

    def _on_category_changed(self, row):
        item = self._category_list.item(row)
        if item is None:
            return
        self._current_category = item.data(Qt.ItemDataRole.UserRole)
        self._all_mods = mod_catalog.get_mods(self._current_category)
        self._search.blockSignals(True)
        self._search.clear()
        self._search.blockSignals(False)
        self._rebuild_grid()

    def _on_search_changed(self, _text):
        self._rebuild_grid()

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

        shown = filtered[:MODS_PER_PAGE]
        for i, mod in enumerate(shown):
            card = _ModCard(self._current_category, mod)
            self._grid.addWidget(card, i // GRID_COLUMNS, i % GRID_COLUMNS)

        if not filtered:
            self._status_label.setText("Ничего не найдено")
        elif len(filtered) > MODS_PER_PAGE:
            self._status_label.setText(
                f"Показаны первые {MODS_PER_PAGE} из {len(filtered)} — уточни поиск"
            )
        else:
            self._status_label.setText(f"{len(filtered)} модов")
