"""Small pieces shared across the hub's own windows (launcher.py) and the
МОДЫ tab's sub-modules (mods_page.py, tools_panel.py) - kept here instead
of duplicated per-file (which is what the first two copies did, before a
third caller made that not worth it anymore) or imported from launcher.py
directly (which would be circular - launcher.py imports mods_page.py to
build its МОДЫ tab)."""
from PyQt6.QtCore import QThread, pyqtSignal

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
