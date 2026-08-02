"""Small window listing OpenDota nickname-search candidates for the user
to pick the right account from, since nicknames aren't unique. Reuses the
overlay's own dark-gradient styling for visual consistency."""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

from overlay_window import _GradientPanel


class CandidatePickerWindow(QWidget):
    def __init__(self, on_selected):
        super().__init__()
        self._on_selected = on_selected
        self.setWindowTitle("Выбери профиль")
        self.resize(360, 300)

        self._panel = _GradientPanel()
        self._layout = QVBoxLayout(self._panel)
        self._layout.setContentsMargins(16, 14, 16, 14)
        self._layout.setSpacing(6)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self._panel)

        title = QLabel("Несколько совпадений — выбери нужного")
        title.setWordWrap(True)
        title.setStyleSheet(
            "color: white; font-weight: bold; font-family: sans-serif; font-size: 13px;"
        )
        self._layout.addWidget(title)

    def show_candidates(self, candidates):
        while self._layout.count() > 1:
            item = self._layout.takeAt(1)
            widget = item.widget()
            if widget:
                widget.hide()
                widget.deleteLater()

        for candidate in candidates:
            btn = QPushButton(candidate["nickname"])
            btn.setStyleSheet(
                "QPushButton { text-align: left; color: white; background-color: rgba(255,255,255,12); "
                "border: none; border-radius: 6px; padding: 8px; font-family: sans-serif; font-size: 13px; }"
                "QPushButton:hover { background-color: rgba(255,255,255,22); }"
            )
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda checked=False, c=candidate: self._select(c))
            self._layout.addWidget(btn)

        self.show()

    def _select(self, candidate):
        self.close()
        self._on_selected(candidate)
