"""Инструменты panel, mounted inside the МОДЫ tab: thin native front-end
over mod_tools.py's console binaries - pack/unpack a .vpk, merge several
.vpk into one, build a custom main-menu background from your own video or
photo. Every action runs on its own throwaway QThread (ui_common.Worker)
since all three shell out to a subprocess and none of that may block the
Qt event loop."""
import os
import shutil
import tempfile

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFileDialog, QFrame, QHBoxLayout, QLabel, QMessageBox, QPushButton,
    QVBoxLayout,
)

import mod_manager
import mod_tools
import platform_utils
from ui_common import PRIMARY_BUTTON_STYLE, SECONDARY_BUTTON_STYLE, Worker

_MEDIA_FILTER = (
    "Видео/фото (*.mp4 *.avi *.mkv *.mov *.wmv *.flv *.webm "
    "*.jpg *.jpeg *.png *.bmp *.gif)"
)


class _ToolsPanel(QFrame):
    def __init__(self):
        super().__init__()
        self._worker = None
        self.setObjectName("toolsPanel")
        self.setStyleSheet(
            "QFrame#toolsPanel { background-color: rgba(255,255,255,6); "
            "border-radius: 12px; border: 1px dashed rgba(255,255,255,20); }"
        )
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 10, 12, 10)
        outer.setSpacing(6)

        title = QLabel("🛠 Инструменты (консольные, github.com/h6rd)")
        title.setStyleSheet(
            "color: #cccccc; font-family: 'Inter'; font-size: 11px; "
            "font-weight: 700; background: transparent;"
        )
        outer.addWidget(title)

        row = QHBoxLayout()
        row.setSpacing(6)
        unpack_btn = QPushButton("Распаковать VPK")
        unpack_btn.setStyleSheet(SECONDARY_BUTTON_STYLE)
        unpack_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        unpack_btn.clicked.connect(self._on_unpack)
        row.addWidget(unpack_btn)

        pack_btn = QPushButton("Упаковать в VPK")
        pack_btn.setStyleSheet(SECONDARY_BUTTON_STYLE)
        pack_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        pack_btn.clicked.connect(self._on_pack)
        row.addWidget(pack_btn)

        merge_btn = QPushButton("Объединить VPK")
        merge_btn.setStyleSheet(SECONDARY_BUTTON_STYLE)
        merge_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        merge_btn.clicked.connect(self._on_merge)
        row.addWidget(merge_btn)

        bg_btn = QPushButton("Свой фон меню")
        bg_btn.setStyleSheet(SECONDARY_BUTTON_STYLE)
        bg_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        bg_btn.clicked.connect(self._on_background)
        # The real Windows build of this tool (Changer.exe) is a GUI app
        # with no CLI to automate - greyed out upfront (and kept that way
        # through every _set_busy() re-enable, see there) rather than only
        # failing after a click, so it doesn't look broken/flaky.
        self._bg_available = not platform_utils.IS_WINDOWS
        if not self._bg_available:
            bg_btn.setEnabled(False)
            bg_btn.setToolTip(
                "На Windows это отдельная GUI-программа — скачай Changer.exe с сайта каталога"
            )
        row.addWidget(bg_btn)
        self._bg_btn = bg_btn

        row.addStretch()
        outer.addLayout(row)

        self._buttons = [unpack_btn, pack_btn, merge_btn, bg_btn]

        self._status_label = QLabel("")
        self._status_label.setWordWrap(True)
        self._status_label.setStyleSheet(
            "color: #999999; font-family: 'Inter'; font-size: 10px; background: transparent;"
        )
        outer.addWidget(self._status_label)

    def _set_busy(self, busy, message=""):
        for btn in self._buttons:
            if btn is self._bg_btn and not self._bg_available:
                continue  # permanently disabled on this platform, not a busy-state toggle
            btn.setEnabled(not busy)
        if message:
            self._status_label.setText(message)

    def _run_async(self, fn, on_success):
        self._set_busy(True, "Работаю...")
        self._worker = Worker(fn)
        self._worker.done.connect(lambda result: self._on_worker_done(result, on_success))
        self._worker.start()

    def _on_worker_done(self, result, on_success):
        self._set_busy(False)
        if isinstance(result, mod_tools.ToolError):
            self._status_label.setText(f"Ошибка: {result}")
            return
        if isinstance(result, Exception):
            self._status_label.setText("Неожиданная ошибка, попробуй ещё раз")
            return
        on_success(result)

    def _offer_install_or_save(self, category_id, display_name, produced_paths):
        """Common tail for pack/merge/background: ask whether to drop the
        result straight into Dota (via mod_manager, so it's tracked and
        uninstallable like any other mod) or just save it to a folder the
        user picks."""
        choice = QMessageBox.question(
            self, "Готово",
            f"Файл создан ({len(produced_paths)} шт). Установить сразу в Dota?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if choice == QMessageBox.StandardButton.Yes:
            ok, message = mod_manager.install_from_files(category_id, display_name, produced_paths)
            self._status_label.setText(message)
            return
        dest_dir = QFileDialog.getExistingDirectory(self, "Куда сохранить")
        if not dest_dir:
            self._status_label.setText(f"Готово, файлы остались во временной папке: {produced_paths[0]}")
            return
        for path in produced_paths:
            shutil.copy2(path, os.path.join(dest_dir, os.path.basename(path)))
        self._status_label.setText(f"Сохранено: {dest_dir}")

    def _on_unpack(self):
        vpk_path, _ = QFileDialog.getOpenFileName(self, "Выбери .vpk", "", "VPK files (*.vpk)")
        if not vpk_path:
            return
        dest_dir = QFileDialog.getExistingDirectory(self, "Куда распаковать")
        if not dest_dir:
            return
        self._run_async(
            lambda: mod_tools.unpack_vpk(vpk_path, dest_dir),
            lambda extracted: self._status_label.setText(f"Распаковано {len(extracted)} файлов в {dest_dir}"),
        )

    def _on_pack(self):
        src_dir = QFileDialog.getExistingDirectory(self, "Папка с файлами для упаковки")
        if not src_dir:
            return
        name = os.path.basename(src_dir.rstrip("/")) or "Мой VPK"
        self._run_async(
            lambda: mod_tools.pack_to_vpk(src_dir, tempfile.mkdtemp(prefix="modtools-out-")),
            lambda produced: self._offer_install_or_save("tools", name, produced),
        )

    def _on_merge(self):
        vpk_paths, _ = QFileDialog.getOpenFileNames(self, "Выбери 2+ .vpk", "", "VPK files (*.vpk)")
        if len(vpk_paths) < 2:
            if vpk_paths:
                self._status_label.setText("Нужно минимум 2 файла для объединения")
            return
        self._run_async(
            lambda: mod_tools.merge_vpks(vpk_paths, tempfile.mkdtemp(prefix="modtools-out-")),
            lambda produced: self._offer_install_or_save("tools", "Объединённый VPK", produced),
        )

    def _on_background(self):
        if not mod_tools.background_changer_available():
            self._status_label.setText("Нужен ffmpeg: sudo pacman -S ffmpeg")
            return
        media_path, _ = QFileDialog.getOpenFileName(self, "Выбери видео или фото", "", _MEDIA_FILTER)
        if not media_path:
            return
        name = f"Фон меню ({os.path.basename(media_path)})"
        self._set_busy(True, "Конвертирую и собираю VPK (может занять минуту)...")
        self._run_async(
            lambda: mod_tools.create_background(media_path, tempfile.mkdtemp(prefix="modtools-out-")),
            lambda produced: self._offer_install_or_save("tools", name, produced),
        )
