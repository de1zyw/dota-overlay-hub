"""Fullscreen drag-to-select calibration of the profile-lookup OCR region.
Shown via a hotkey while a real Dota profile screen is visible.

Grabs a real screenshot BEFORE showing itself and paints that as an
opaque backdrop, rather than rendering as a live translucent window on
top of the game. A live-transparent window (WA_TranslucentBackground)
depends on a compositor being active to blend correctly - without one
(common on tiling WMs like i3/dwm/bspwm without picom running), Qt just
paints solid black instead of see-through, which made the game
underneath invisible and selection impossible. A static screenshot
backdrop sidesteps that dependency entirely: it's just a normal opaque
image, no compositing involved."""
from PyQt6.QtCore import QRect, Qt
from PyQt6.QtGui import QColor, QGuiApplication, QPainter, QPen
from PyQt6.QtWidgets import QWidget

import profile_lookup_settings


class RegionCalibrator(QWidget):
    def __init__(self, on_done):
        super().__init__()
        self._on_done = on_done
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setCursor(Qt.CursorShape.CrossCursor)
        self._start = None
        self._current = None

        screen = QGuiApplication.primaryScreen()
        # Grabbed BEFORE showFullScreen() so this window itself isn't in
        # the shot - grabWindow(0) captures the whole screen's current
        # framebuffer contents directly, independent of any compositor.
        self._backdrop = screen.grabWindow(0) if screen else None

        self.showFullScreen()

    def paintEvent(self, event):
        painter = QPainter(self)
        if self._backdrop is not None:
            painter.drawPixmap(self.rect(), self._backdrop)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 60))
        if self._start and self._current:
            rect = QRect(self._start, self._current).normalized()
            painter.setPen(QPen(QColor("#7DD3FC"), 2))
            painter.fillRect(rect, QColor(255, 255, 255, 30))
            painter.drawRect(rect)

    def mousePressEvent(self, event):
        self._start = event.pos()
        self._current = event.pos()
        self.update()

    def mouseMoveEvent(self, event):
        if self._start:
            self._current = event.pos()
            self.update()

    def mouseReleaseEvent(self, event):
        if not self._start:
            return
        rect = QRect(self._start, event.pos()).normalized()
        self.close()
        if rect.width() > 4 and rect.height() > 4:
            top_left = self.mapToGlobal(rect.topLeft())
            region = {
                "x": top_left.x(), "y": top_left.y(),
                "width": rect.width(), "height": rect.height(),
            }
            profile_lookup_settings.save(region)
            self._on_done(region)
        else:
            self._on_done(None)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            self._on_done(None)
