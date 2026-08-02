"""Dedicated on-demand window showing the local user's own OpenDota stats
in more detail than a draft row - bigger overall numbers, 10 recent
matches instead of 5 (two rows of 5). Toggled by a hotkey, independent of
match state. Reuses overlay_window.py's private helpers for the same
dark-gradient visual style rather than duplicating that rendering code."""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

import config
from assets import get_rank_icon_path
from overlay_window import _GradientPanel, _icon_label, _match_history_group, _winrate_color

RANK_ICON_SIZE = 48


class SelfStatsWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowOpacity(config.WINDOW_OPACITY)

        self._panel = _GradientPanel()
        self._layout = QVBoxLayout(self._panel)
        self._layout.setContentsMargins(20, 18, 20, 18)
        self._layout.setSpacing(8)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self._panel)

        self.move(config.WINDOW_MARGIN_PX, config.WINDOW_MARGIN_PX)

    def _clear_layout(self):
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

    def render_stats(self, stats):
        self._clear_layout()

        if stats is None:
            msg = QLabel("Steam-аккаунт не определён — стата недоступна")
            msg.setStyleSheet("color: #aaaaaa; font-family: sans-serif; font-size: 13px;")
            self._layout.addWidget(msg)
            self._panel.adjustSize()
            self.adjustSize()
            return

        header = QHBoxLayout()
        header.addWidget(_icon_label(get_rank_icon_path(stats.rank_tier), RANK_ICON_SIZE))
        nickname = QLabel(stats.nickname)
        nickname.setStyleSheet(
            "color: white; font-weight: bold; font-family: sans-serif; font-size: 20px;"
        )
        header.addWidget(nickname)
        header.addStretch()
        self._layout.addLayout(header)

        winrate_str = f"{stats.winrate:.0f}%" if stats.winrate is not None else "н/д"
        overall = QLabel(f"WR {winrate_str}  •  {stats.total_games} игр")
        overall.setStyleSheet(
            f"color: {_winrate_color(stats.winrate)}; font-family: sans-serif; "
            "font-size: 18px; font-weight: 600;"
        )
        self._layout.addWidget(overall)

        history_label = QLabel("ПОСЛЕДНИЕ МАТЧИ")
        history_label.setStyleSheet(
            "color: #888899; font-family: sans-serif; font-size: 11px; "
            "font-weight: bold; letter-spacing: 1px;"
        )
        self._layout.addWidget(history_label)

        self._layout.addWidget(_match_history_group(stats.recent_matches[0:5]))
        self._layout.addWidget(_match_history_group(stats.recent_matches[5:10]))

        self._panel.adjustSize()
        self.adjustSize()

    def show_stats(self):
        self.show()

    def hide_stats(self):
        self.hide()

    def toggle(self):
        if self.isVisible():
            self.hide_stats()
        else:
            self.show_stats()
