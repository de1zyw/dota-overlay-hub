"""Cart dialog for the МОДЫ tab - review the currently checkbox-selected
mods (across any category), optionally save/load them as a named preset
(mod_presets.py), then install them all in one batch run with a step-by-
step progress log. Modeled on the reference catalog's own cart/pack UI
(a screenshot the user shared, 2026-08-09) but installs directly instead
of producing a downloadable zip - this app already has its own real
installer (mod_manager.py), no reason to hand the user a zip to deal
with by hand afterward."""
import math
import os

from PyQt6.QtCore import QPointF, Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap
from PyQt6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QInputDialog, QLabel, QListWidget,
    QListWidgetItem, QMessageBox, QPushButton, QScrollArea, QVBoxLayout,
    QWidget,
)

import mod_catalog
import mod_manager
import mod_presets
from ui_common import PRIMARY_BUTTON_STYLE, SCROLLBAR_STYLE, SECONDARY_BUTTON_STYLE, Worker

ITEM_THUMB_SIZE = 48


class _WaveProgressBar(QWidget):
    """Animated pill progress bar for the batch-install log, matching the
    reference d2pfx catalog's own "Packing Progress" dialog (a screenshot
    the user shared 2026-08-09): the filled portion is a tight, angular
    zigzag in a single solid purple (not a smooth sine, not a multi-color
    gradient) that keeps travelling while the batch is actively running,
    a thin flat track continues for the unfilled remainder, and a small
    white dot marks the boundary between them. Settles into a flat solid
    fill once the batch finishes so it doesn't keep looking like it's
    still working after it's done."""
    _WAVELENGTH = 9.0
    _AMPLITUDE = 4.0
    _PHASE_STEP = 4.0
    _FILL_COLOR = QColor("#B388FF")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(14)
        self._fraction = 0.0
        self._active = False
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(35)
        self._timer.timeout.connect(self._tick)

    def set_progress(self, done, total):
        self._fraction = (done / total) if total else 0.0
        self.update()

    def set_active(self, active):
        self._active = active
        if active:
            self._timer.start()
        else:
            self._timer.stop()
        self.update()

    def _tick(self):
        self._phase += self._PHASE_STEP
        self.update()

    def _wave_y(self, x, mid):
        # Triangle wave, not sine - a tighter, more angular "squiggle"
        # closer to the reference site's own zigzag than a smooth curve.
        t = ((x + self._phase) % self._WAVELENGTH) / self._WAVELENGTH
        triangle = 4 * abs(t - 0.5) - 1  # ranges -1..1
        return mid + self._AMPLITUDE * triangle

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()
        mid = self.height() / 2
        fill_x = max(0.0, min(w, self._fraction * w))

        if fill_x < w:
            track_pen = QPen(QColor(255, 255, 255, 35))
            track_pen.setWidth(2)
            track_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(track_pen)
            painter.drawLine(QPointF(fill_x, mid), QPointF(w, mid))

        if fill_x > 0:
            fill_pen = QPen(self._FILL_COLOR, 3)
            fill_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            fill_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(fill_pen)
            path = QPainterPath()
            if self._active:
                x = 0.0
                path.moveTo(0, self._wave_y(0, mid))
                while x < fill_x:
                    x = min(x + 2.0, fill_x)
                    path.lineTo(x, self._wave_y(x, mid))
            else:
                path.moveTo(0, mid)
                path.lineTo(fill_x, mid)
            painter.drawPath(path)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255, 235))
        end_y = self._wave_y(fill_x, mid) if self._active else mid
        painter.drawEllipse(QPointF(fill_x, end_y), 3, 3)


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
                installer = (
                    mod_manager.install_loose_mod if mod_manager.is_loose_file_category(category_id)
                    else mod_manager.install_mod
                )
                ok, _message = installer(category_id, mod)
            except Exception:  # noqa: BLE001 - one bad mod shouldn't kill the queue
                ok = False
            self.progress.emit(i, total, mod["name"], ok)
        self.finished_all.emit()


class _CartItemRow(QFrame):
    def __init__(self, category_id, mod, on_remove):
        super().__init__()
        self.setStyleSheet(
            "QFrame { background-color: rgba(255,255,255,8); border-radius: 8px; }"
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(10)

        self._thumb = QLabel()
        self._thumb.setFixedSize(ITEM_THUMB_SIZE, ITEM_THUMB_SIZE)
        self._thumb.setStyleSheet("background-color: rgba(0,0,0,60); border-radius: 6px;")
        self._thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._thumb)

        text_col = QVBoxLayout()
        text_col.setSpacing(0)
        name_label = QLabel(mod["name"])
        name_label.setStyleSheet(
            "color: white; font-family: 'Inter'; font-size: 12px; "
            "font-weight: 700; background: transparent;"
        )
        text_col.addWidget(name_label)
        cat_label = QLabel(category_id)
        cat_label.setStyleSheet(
            "color: #999999; font-family: 'Inter'; font-size: 10px; background: transparent;"
        )
        text_col.addWidget(cat_label)
        layout.addLayout(text_col, 1)

        remove_btn = QPushButton("✕")
        remove_btn.setFixedSize(26, 26)
        remove_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        remove_btn.setStyleSheet(
            "QPushButton { background-color: rgba(255,255,255,10); color: #cccccc; "
            "border: none; border-radius: 13px; font-family: 'Inter'; font-size: 12px; }"
            "QPushButton:hover { background-color: rgba(226,87,76,60); color: white; }"
        )
        remove_btn.clicked.connect(lambda: on_remove(category_id, mod["name"]))
        layout.addWidget(remove_btn)

        self._worker = None
        preview = mod.get("preview")
        if preview:
            self._worker = Worker(lambda: mod_catalog.get_preview_path(category_id, preview))
            self._worker.done.connect(self._on_preview_loaded)
            self._worker.start()

    def _on_preview_loaded(self, path):
        if not isinstance(path, str) or not os.path.exists(path):
            return
        pixmap = QPixmap(path)
        if pixmap.isNull():
            return
        scaled = pixmap.scaled(
            self._thumb.width(), self._thumb.height(),
            Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation,
        )
        self._thumb.setPixmap(scaled)


class CartDialog(QDialog):
    """`selected` is the SAME dict object as _ModsPage._selected - mutated
    in place (item removal, cleared after a successful install), so the
    page behind this dialog reflects the change the moment it closes,
    with no separate sync step needed. `on_change` is called after every
    mutation so the caller can refresh its own batch-button label/card
    checkboxes."""
    def __init__(self, parent, selected, on_change):
        super().__init__(parent)
        self._selected = selected
        self._on_change = on_change
        self._batch_worker = None

        self.setWindowTitle("Корзина модов")
        self.resize(900, 620)
        self.setStyleSheet("QDialog { background-color: #1a1a24; }")

        root = QHBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(16)

        # --- left: saved presets ---
        left = QVBoxLayout()
        left.setSpacing(8)
        presets_title = QLabel("НАБОРЫ")
        presets_title.setStyleSheet(
            "color: #999999; font-family: 'Inter'; font-size: 11px; "
            "font-weight: 700; letter-spacing: 1px;"
        )
        left.addWidget(presets_title)

        self._presets_list = QListWidget()
        self._presets_list.setFixedWidth(200)
        self._presets_list.setStyleSheet(
            "QListWidget { background-color: rgba(255,255,255,6); color: white; "
            "font-family: 'Inter'; font-size: 12px; border: none; border-radius: 8px; }"
            "QListWidget::item { padding: 8px; border-radius: 4px; }"
            "QListWidget::item:selected { background-color: rgba(255,255,255,20); }"
            + SCROLLBAR_STYLE
        )
        left.addWidget(self._presets_list, 1)

        preset_buttons = QHBoxLayout()
        load_preset_btn = QPushButton("Загрузить")
        load_preset_btn.setStyleSheet(SECONDARY_BUTTON_STYLE)
        load_preset_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        load_preset_btn.clicked.connect(self._on_load_preset)
        preset_buttons.addWidget(load_preset_btn)
        delete_preset_btn = QPushButton("Удалить")
        delete_preset_btn.setStyleSheet(SECONDARY_BUTTON_STYLE)
        delete_preset_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        delete_preset_btn.clicked.connect(self._on_delete_preset)
        preset_buttons.addWidget(delete_preset_btn)
        left.addLayout(preset_buttons)
        root.addLayout(left)

        # --- right: cart items + actions + progress log ---
        right = QVBoxLayout()
        right.setSpacing(10)

        cart_title = QLabel("КОРЗИНА")
        cart_title.setStyleSheet(
            "color: #999999; font-family: 'Inter'; font-size: 11px; "
            "font-weight: 700; letter-spacing: 1px;"
        )
        right.addWidget(cart_title)

        self._items_host = QWidget()
        self._items_layout = QVBoxLayout(self._items_host)
        self._items_layout.setSpacing(6)
        self._items_layout.addStretch()
        items_scroll = QScrollArea()
        items_scroll.setWidget(self._items_host)
        items_scroll.setWidgetResizable(True)
        items_scroll.setFrameShape(QFrame.Shape.NoFrame)
        items_scroll.setStyleSheet(
            "QScrollArea { background: transparent; } "
            "QScrollArea > QWidget > QWidget { background: transparent; }"
            + SCROLLBAR_STYLE
        )
        right.addWidget(items_scroll, 1)

        self._empty_label = QLabel("Корзина пуста — отметь моды галочками в каталоге")
        self._empty_label.setStyleSheet("color: #777777; font-family: 'Inter'; font-size: 12px;")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        right.addWidget(self._empty_label)

        action_row = QHBoxLayout()
        save_btn = QPushButton("Сохранить набор")
        save_btn.setStyleSheet(SECONDARY_BUTTON_STYLE)
        save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        save_btn.clicked.connect(self._on_save_pack)
        action_row.addWidget(save_btn)
        clear_btn = QPushButton("Очистить")
        clear_btn.setStyleSheet(SECONDARY_BUTTON_STYLE)
        clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        clear_btn.clicked.connect(self._on_clear)
        action_row.addWidget(clear_btn)
        action_row.addStretch()
        self._install_btn = QPushButton()
        self._install_btn.setStyleSheet(PRIMARY_BUTTON_STYLE)
        self._install_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._install_btn.clicked.connect(self._on_install)
        action_row.addWidget(self._install_btn)
        right.addLayout(action_row)

        self._progress_panel = QFrame()
        self._progress_panel.setObjectName("progressPanel")
        self._progress_panel.setStyleSheet(
            "QFrame#progressPanel { background-color: rgba(0,0,0,30); border-radius: 10px; }"
        )
        progress_layout = QVBoxLayout(self._progress_panel)
        progress_layout.setContentsMargins(12, 10, 12, 10)
        progress_layout.setSpacing(8)

        progress_title = QLabel("⚙ Прогресс установки")
        progress_title.setStyleSheet(
            "color: white; font-family: 'Inter'; font-size: 12px; font-weight: 700; "
            "background: transparent;"
        )
        progress_layout.addWidget(progress_title)

        self._log_host = QWidget()
        self._log_layout = QVBoxLayout(self._log_host)
        self._log_layout.setSpacing(3)
        self._log_layout.addStretch()
        self._log_scroll = QScrollArea()
        self._log_scroll.setWidget(self._log_host)
        self._log_scroll.setWidgetResizable(True)
        self._log_scroll.setFixedHeight(130)
        self._log_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._log_scroll.setStyleSheet(
            "QScrollArea { background: transparent; } "
            "QScrollArea > QWidget > QWidget { background: transparent; }"
            + SCROLLBAR_STYLE
        )
        progress_layout.addWidget(self._log_scroll)

        self._progress_status_label = QLabel("")
        self._progress_status_label.setStyleSheet(
            "color: #999999; font-family: 'Inter'; font-size: 11px; background: transparent;"
        )
        progress_layout.addWidget(self._progress_status_label)

        self._progress_bar = _WaveProgressBar()
        progress_layout.addWidget(self._progress_bar)

        self._progress_panel.hide()
        right.addWidget(self._progress_panel)

        root.addLayout(right, 1)

        self._refresh_presets_list()
        self._refresh_items()

    # --- cart items ---

    def _refresh_items(self):
        while self._items_layout.count() > 1:  # keep the trailing stretch
            item = self._items_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.hide()
                widget.deleteLater()

        for (category_id, _mod_name), mod in self._selected.items():
            row = _CartItemRow(category_id, mod, self._on_remove_item)
            self._items_layout.insertWidget(self._items_layout.count() - 1, row)

        count = len(self._selected)
        self._empty_label.setVisible(count == 0)
        self._install_btn.setText(f"Установить ({count})" if count else "Установить")
        self._install_btn.setEnabled(count > 0)

    def _on_remove_item(self, category_id, mod_name):
        self._selected.pop((category_id, mod_name), None)
        self._on_change()
        self._refresh_items()

    def _on_clear(self):
        self._selected.clear()
        self._on_change()
        self._refresh_items()

    # --- presets ---

    def _refresh_presets_list(self):
        self._presets_list.clear()
        presets = mod_presets.load_all()
        if not presets:
            item = QListWidgetItem("Нет сохранённых наборов")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self._presets_list.addItem(item)
            return
        for name, items in presets.items():
            self._presets_list.addItem(f"{name} ({len(items)})")

    def _selected_preset_name(self):
        row = self._presets_list.currentRow()
        presets = list(mod_presets.load_all().keys())
        if 0 <= row < len(presets):
            return presets[row]
        return None

    def _on_save_pack(self):
        if not self._selected:
            return
        name, ok = QInputDialog.getText(self, "Сохранить набор", "Имя набора:")
        if not ok or not name.strip():
            return
        mod_presets.save(name, list(self._selected.keys()))
        self._refresh_presets_list()

    def _on_load_preset(self):
        name = self._selected_preset_name()
        if not name:
            return
        items = mod_presets.load_all().get(name, [])
        missing = []
        for category_id, mod_name in items:
            mod = next(
                (m for m in mod_catalog.get_mods(category_id) if m["name"] == mod_name), None,
            )
            if mod is None:
                missing.append(mod_name)
                continue
            self._selected[(category_id, mod_name)] = mod
        self._on_change()
        self._refresh_items()
        if missing:
            QMessageBox.information(
                self, "Набор загружен",
                f"{len(missing)} мод(ов) из набора больше нет в каталоге, пропущены:\n"
                + "\n".join(missing),
            )

    def _on_delete_preset(self):
        name = self._selected_preset_name()
        if not name:
            return
        mod_presets.delete(name)
        self._refresh_presets_list()

    # --- install progress log ---

    def _clear_log(self):
        while self._log_layout.count() > 1:  # keep the trailing stretch
            item = self._log_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

    def _add_log_row(self, icon, html_text):
        row = QLabel(f"{icon}&nbsp;&nbsp;{html_text}")
        row.setTextFormat(Qt.TextFormat.RichText)
        row.setStyleSheet(
            "color: #cccccc; font-family: 'Inter'; font-size: 11px; background: transparent;"
        )
        self._log_layout.insertWidget(self._log_layout.count() - 1, row)
        # Layout hasn't recomputed the scroll range yet on this call - defer
        # the scroll-to-bottom to the next event-loop tick, same trick as
        # elsewhere in this app for "scroll after content just changed".
        QTimer.singleShot(0, lambda: self._log_scroll.verticalScrollBar().setValue(
            self._log_scroll.verticalScrollBar().maximum()
        ))

    # --- install ---

    def _on_install(self):
        jobs = list(self._selected.items())
        if not jobs:
            return
        self._install_btn.setEnabled(False)
        self._clear_log()
        self._progress_panel.show()
        self._progress_bar.set_progress(0, len(jobs))
        self._progress_bar.set_active(True)
        self._progress_status_label.setText(f"Обрабатываю 0/{len(jobs)} мод(ов)...")
        self._add_log_row("🚀", "Начинаю установку...")
        self._add_log_row("📦", f"В очереди: <b>{len(jobs)}</b> мод(ов)")
        self._batch_worker = _BatchInstallWorker([(cat, mod) for (cat, _name), mod in jobs])
        self._batch_worker.progress.connect(self._on_progress)
        self._batch_worker.finished_all.connect(self._on_install_finished)
        self._batch_worker.start()

    def _on_progress(self, done, total, mod_name, ok):
        if ok:
            self._add_log_row("✅", f'Установлен <b style="color:#a3e6a3;">{mod_name}</b>')
        else:
            self._add_log_row("❌", f'Не удалось: <b style="color:#e2574c;">{mod_name}</b>')
        self._progress_bar.set_progress(done, total)
        self._progress_status_label.setText(f"Обрабатываю {done}/{total} мод(ов)...")

    def _on_install_finished(self):
        self._progress_bar.set_active(False)
        self._progress_bar.set_progress(1, 1)
        self._progress_status_label.setText("Готово!")
        self._add_log_row("🎉", "<b>Готово</b> — все моды обработаны!")
        self._selected.clear()
        self._on_change()
        self._refresh_items()
