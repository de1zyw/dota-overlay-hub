"""МОДЫ tab: browses the open Dota2PornFx mod catalog (mod_catalog.py) and
installs/removes cosmetic mods via mod_manager.py. Preview downloads and
install/uninstall both hit the network - each runs on its own throwaway
QThread so neither ever blocks the Qt event loop.

Mods can be installed one at a time (each card's own button) or picked
via checkbox across any number of categories and installed in one batch
run - the batch queue survives switching categories (tracked in
_ModsPage._selected, keyed by (category_id, mod_name), independent of any
one _ModCard's lifetime since the grid is rebuilt on every category/search
change)."""
import os

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QFrame, QGridLayout, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QPushButton, QScrollArea,
    QVBoxLayout, QWidget,
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
            "QFrame#modCard { background-color: rgba(255,255,255,10); border-radius: 8px; }"
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
            "color: white; font-family: sans-serif; font-size: 11px; "
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
            "color: #999999; font-family: sans-serif; font-size: 10px; background: transparent;"
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


class _ModsPage(QWidget):
    def __init__(self):
        super().__init__()
        self._current_category = None
        self._all_mods = []
        # {(category_id, mod_name): mod} - the batch-install queue. Kept
        # here, not on individual cards, so it survives switching category
        # (the grid, and every _ModCard in it, gets thrown away and rebuilt
        # on every category/search change).
        self._selected = {}
        self._batch_worker = None

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

        os_bar = QHBoxLayout()
        os_label = QLabel("Платформа:")
        os_label.setStyleSheet("color: #aaaaaa; font-family: sans-serif; font-size: 11px;")
        os_bar.addWidget(os_label)
        os_bar.addWidget(_os_toggle_button("🐧 Linux", active=True))
        windows_btn = _os_toggle_button("🔒 Windows", active=False)
        windows_btn.setToolTip("Скоро — заработает после установки Windows на отдельный диск")
        os_bar.addWidget(windows_btn)
        os_bar.addStretch()
        right.addLayout(os_bar)

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

        search_bar = QHBoxLayout()
        self._search = QLineEdit()
        self._search.setPlaceholderText("Поиск по названию...")
        self._search.setStyleSheet(
            "QLineEdit { background-color: rgba(255,255,255,10); color: white; "
            "border: 1px solid rgba(255,255,255,30); border-radius: 4px; padding: 6px 10px; "
            "font-family: sans-serif; font-size: 12px; }"
        )
        self._search.textChanged.connect(self._on_search_changed)
        search_bar.addWidget(self._search, 1)

        self._clear_selection_btn = QPushButton("Очистить выбор")
        self._clear_selection_btn.setStyleSheet(SECONDARY_BUTTON_STYLE)
        self._clear_selection_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._clear_selection_btn.clicked.connect(self._clear_selection)
        search_bar.addWidget(self._clear_selection_btn)

        self._batch_btn = QPushButton()
        self._batch_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._batch_btn.clicked.connect(self._start_batch_install)
        search_bar.addWidget(self._batch_btn)
        right.addLayout(search_bar)

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

        self._update_batch_button()
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

    def _on_card_toggle(self, category_id, mod, checked):
        key = (category_id, mod["name"])
        if checked:
            self._selected[key] = mod
        else:
            self._selected.pop(key, None)
        self._update_batch_button()

    def _update_batch_button(self):
        count = len(self._selected)
        self._batch_btn.setText(f"Установить выбранное ({count})" if count else "Установить выбранное")
        self._batch_btn.setEnabled(count > 0)
        self._batch_btn.setStyleSheet(PRIMARY_BUTTON_STYLE)
        self._clear_selection_btn.setEnabled(count > 0)

    def _clear_selection(self):
        self._selected = {}
        self._update_batch_button()
        self._rebuild_grid()

    def _start_batch_install(self):
        jobs = list(self._selected.items())
        if not jobs:
            return
        self._batch_btn.setEnabled(False)
        self._clear_selection_btn.setEnabled(False)
        self._batch_worker = _BatchInstallWorker([(cat, mod) for (cat, _name), mod in jobs])
        self._batch_worker.progress.connect(self._on_batch_progress)
        self._batch_worker.finished_all.connect(self._on_batch_finished)
        self._batch_worker.start()

    def _on_batch_progress(self, done, total, mod_name, ok):
        verdict = "OK" if ok else "ошибка"
        self._status_label.setText(f"Установка {done}/{total}: {mod_name} — {verdict}")

    def _on_batch_finished(self):
        self._selected = {}
        self._update_batch_button()
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
            key = (self._current_category, mod["name"])
            card = _ModCard(
                self._current_category, mod,
                checked=key in self._selected,
                on_toggle=self._on_card_toggle,
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
