"""Small pieces shared across the hub's own windows (launcher.py) and the
МОДЫ tab's sub-modules (mods_page.py, tools_panel.py) - kept here instead
of duplicated per-file (which is what the first two copies did, before a
third caller made that not worth it anymore) or imported from launcher.py
directly (which would be circular - launcher.py imports mods_page.py to
build its МОДЫ tab)."""
from PyQt6.QtCore import QPropertyAnimation, QThread, Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import QApplication, QGraphicsOpacityEffect, QLabel

SECONDARY_BUTTON_STYLE = """
QPushButton {
    background-color: rgba(255, 255, 255, 15);
    color: #dddddd;
    border: 1px solid rgba(255, 255, 255, 30);
    border-radius: 8px;
    padding: 8px 16px;
    font-family: 'Inter';
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
    border-radius: 8px;
    padding: 8px 16px;
    font-family: 'Inter';
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

# The platform's native scrollbar (grey track, arrow buttons at each end)
# doesn't match anything else in this app's own dark/rounded visual
# language - append to any QScrollArea's own stylesheet. add-line/sub-
# line's height/width forced to 0 is what actually removes the arrow
# buttons (Qt has no simpler toggle for that); add-page/sub-page set to
# transparent so only the handle itself paints.
SCROLLBAR_STYLE = """
QScrollBar:vertical {
    background: transparent;
    width: 8px;
    margin: 0px;
}
QScrollBar::handle:vertical {
    background: rgba(255, 255, 255, 40);
    border-radius: 4px;
    min-height: 24px;
}
QScrollBar::handle:vertical:hover {
    background: rgba(255, 255, 255, 70);
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
    background: none;
    border: none;
}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: none;
}
QScrollBar:horizontal {
    background: transparent;
    height: 8px;
    margin: 0px;
}
QScrollBar::handle:horizontal {
    background: rgba(255, 255, 255, 40);
    border-radius: 4px;
    min-width: 24px;
}
QScrollBar::handle:horizontal:hover {
    background: rgba(255, 255, 255, 70);
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0px;
    background: none;
    border: none;
}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
    background: none;
}
"""


def animate_button_press(button):
    """Brief opacity dip-and-recover on click - QSS's :pressed color swap
    alone reads as "different state", not "responded to your click", and
    every button here already sits inside a QVBoxLayout/QHBoxLayout, so a
    geometry-based press/bounce animation would fight the layout manager
    repositioning it right back (a real, common Qt gotcha - geometry
    animations only behave on manually-positioned widgets). Opacity via
    QGraphicsOpacityEffect doesn't touch layout at all, same mechanism
    already used for launcher.py's own tab-switch fade. Call this from a
    button's own clicked handler, not connected directly to `clicked`
    (handlers need the click for their real action too)."""
    effect = QGraphicsOpacityEffect(button)
    button.setGraphicsEffect(effect)
    anim = QPropertyAnimation(effect, b"opacity", button)
    anim.setDuration(320)
    anim.setKeyValueAt(0.0, 1.0)
    anim.setKeyValueAt(0.3, 0.15)
    anim.setKeyValueAt(1.0, 1.0)
    # Kept as an attribute (not just a local variable) so Python doesn't
    # garbage-collect the animation object mid-flight - QPropertyAnimation
    # being parented to `button` handles the C++ side, but PyQt's own
    # wrapper needs a live Python reference too.
    button._press_anim = anim

    def _cleanup():
        # A QGraphicsOpacityEffect left attached (even fully opaque, at
        # 1.0) keeps compositing the button through an offscreen pixmap on
        # every repaint - confirmed live: this collided with
        # _WaveProgressBar's own 35ms repaint timer during a real install
        # (the install button's effect was still attached while the
        # dialog kept repainting), spamming "QPainter::begin: A paint
        # device can only be painted by one painter at a time" and stalling
        # real UI updates. Detach once the dip-and-recover is done, not
        # just reset its opacity - a widget with no active effect goes
        # back to the cheap, direct paint path.
        #
        # Only clear it if it's still OUR effect - a second rapid click
        # replaces button.graphicsEffect() with a fresh one (Qt deletes
        # the old one when replaced), and this callback firing late would
        # otherwise rip out that newer, still-animating effect instead.
        if button.graphicsEffect() is effect:
            button.setGraphicsEffect(None)

    anim.finished.connect(_cleanup)
    anim.start()


class _ClickToCopyLabel(QLabel):
    """Read-only multi-line info block (version/platform/etc.) that copies
    its full text to the clipboard on click - a whole-block equivalent of
    the existing "Скопировать путь" button pattern (logs page), but for
    text that's meant to be read AND grabbed as one chunk, not just
    referenced by a separate button next to it."""
    _BASE_STYLE = (
        "QLabel { background-color: rgba(255,255,255,10); color: #dddddd; "
        "border: 1px solid rgba(255,255,255,30); border-radius: 6px; "
        "padding: 8px 12px; font-family: monospace; font-size: 11px; }"
    )
    _FLASH_STYLE = (
        "QLabel { background-color: rgba(179,136,255,40); color: white; "
        "border: 1px solid rgba(179,136,255,90); border-radius: 6px; "
        "padding: 8px 12px; font-family: monospace; font-size: 11px; }"
    )

    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self._full_text = text
        self.setStyleSheet(self._BASE_STYLE)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Нажми, чтобы скопировать")
        self.setWordWrap(True)

    def mousePressEvent(self, event):
        QApplication.clipboard().setText(self._full_text)
        self.setText(self._full_text + "\n\n(скопировано)")
        self.setStyleSheet(self._FLASH_STYLE)
        QTimer.singleShot(900, self._reset_flash)
        super().mousePressEvent(event)

    def _reset_flash(self):
        self.setText(self._full_text)
        self.setStyleSheet(self._BASE_STYLE)


class Worker(QThread):
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
