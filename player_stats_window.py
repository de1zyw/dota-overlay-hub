"""Dedicated on-demand window showing a player's OpenDota stats - used for
both the local user's own stats (self-stats hotkey) and any profile
looked up via OCR. Content is generic; only the caller decides whose
account_id to fetch. Bigger overall numbers than a draft row, 10 recent
matches instead of 5 (two rows of 5). Reuses overlay_window.py's private
helpers for the same dark-gradient visual style rather than duplicating
that rendering code."""
import time

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

import config
import error_codes
import window_position
from assets import get_avatar_path, get_hero_icon_path, get_rank_icon_path
from opendota_client import fetch_peers
from overlay_window import _GradientPanel, _icon_label, _match_history_group, _winrate_color

RANK_ICON_SIZE = 48

# stats.hidden with a given error_reason means "OpenDota itself is the
# problem right now", not "this profile is actually private" - shown as a
# distinct message so the user knows to just wait/retry rather than assume
# the tool (or the other player's settings) is broken. None/unlisted reason
# falls back to the genuine-privacy message below.
_ERROR_REASON_MESSAGES = {
    "network": "Нет связи с OpenDota — проверь интернет-соединение",
    "rate_limited": "OpenDota перегружен (лимит запросов) — попробуй через минуту",
    "server_error": "OpenDota сейчас недоступен (сбой на их стороне) — попробуй позже",
    "invalid_json": "OpenDota вернул повреждённый ответ — попробуй ещё раз",
}
_DEFAULT_HIDDEN_MESSAGE = "Профиль скрыт в приватности Steam или ещё не проиндексирован OpenDota"


class PlayerStatsWindow(QWidget):
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

        self.move(*window_position.compute(self.width(), self.height()))

    def _clear_layout(self):
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

    def render_stats(self, stats, empty_message="Steam-аккаунт не определён — стата недоступна", is_self=False):
        self._clear_layout()

        if stats is None:
            msg = QLabel(empty_message)
            msg.setStyleSheet("color: #aaaaaa; font-family: sans-serif; font-size: 13px;")
            self._layout.addWidget(msg)
            self._panel.adjustSize()
            self.adjustSize()
            return

        if stats.hidden:
            text = _ERROR_REASON_MESSAGES.get(stats.error_reason, _DEFAULT_HIDDEN_MESSAGE)
            if stats.error_code is not None:
                code_tag = (
                    error_codes.http_tag(stats.error_code)
                    if stats.error_code in range(100, 600)
                    else error_codes.tag(stats.error_code)
                )
                text += f" {code_tag}"
            msg = QLabel(text)
            msg.setWordWrap(True)
            msg.setStyleSheet("color: #aaaaaa; font-family: sans-serif; font-size: 13px;")
            self._layout.addWidget(msg)
            self._panel.adjustSize()
            self.adjustSize()
            return

        if stats.stale:
            age_min = max(0, int((time.time() - stats.stale_fetched_at) // 60)) if stats.stale_fetched_at else 0
            age_str = "меньше минуты назад" if age_min < 1 else f"{age_min} мин назад"
            stale_msg = QLabel(f"⚠ Нет связи с OpenDota сейчас — показаны данные от {age_str}")
            stale_msg.setWordWrap(True)
            stale_msg.setStyleSheet(
                "color: #e2c04c; font-family: sans-serif; font-size: 11px; font-weight: 600;"
            )
            self._layout.addWidget(stale_msg)

        header = QHBoxLayout()
        header.addWidget(_icon_label(get_rank_icon_path(stats.rank_tier), RANK_ICON_SIZE))
        if stats.leaderboard_rank is not None:
            leaderboard_badge = QLabel(f"Топ #{stats.leaderboard_rank}")
            leaderboard_badge.setStyleSheet(
                f"color: {config.COLOR_GREEN}; font-family: sans-serif; "
                "font-size: 11px; font-weight: bold;"
            )
            header.addWidget(leaderboard_badge)
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

        self._layout.addWidget(_match_history_group(stats.recent_matches[0:5], show_kda=True))
        self._layout.addWidget(_match_history_group(stats.recent_matches[5:10], show_kda=True))

        if stats.top_heroes:
            top_heroes_label = QLabel("ТОП ГЕРОИ")
            top_heroes_label.setStyleSheet(
                "color: #888899; font-family: sans-serif; font-size: 11px; "
                "font-weight: bold; letter-spacing: 1px;"
            )
            self._layout.addWidget(top_heroes_label)

            top_heroes_row = QWidget()
            top_heroes_layout = QHBoxLayout(top_heroes_row)
            top_heroes_layout.setContentsMargins(0, 0, 0, 0)
            top_heroes_layout.setSpacing(12)
            for hero_id, games, win in stats.top_heroes:
                entry = QWidget()
                entry_layout = QVBoxLayout(entry)
                entry_layout.setContentsMargins(0, 0, 0, 0)
                entry_layout.setSpacing(2)
                entry_layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)
                entry_layout.addWidget(
                    _icon_label(get_hero_icon_path(hero_id), 32), 0, Qt.AlignmentFlag.AlignHCenter
                )
                hero_winrate = (win / games * 100) if games else None
                caption = QLabel(f"{hero_winrate:.0f}% · {games}" if hero_winrate is not None else "н/д")
                caption.setStyleSheet(
                    f"color: {_winrate_color(hero_winrate)}; font-family: sans-serif; font-size: 10px;"
                )
                caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
                entry_layout.addWidget(caption)
                top_heroes_layout.addWidget(entry)
            top_heroes_layout.addStretch()
            self._layout.addWidget(top_heroes_row)

        if is_self:
            peers = fetch_peers(stats.account_id)
            if peers:
                peers_label = QLabel("ЧАСТО ИГРАЕШЬ С")
                peers_label.setStyleSheet(
                    "color: #888899; font-family: sans-serif; font-size: 11px; "
                    "font-weight: bold; letter-spacing: 1px;"
                )
                self._layout.addWidget(peers_label)
                for peer in peers:
                    row = QHBoxLayout()
                    row.addWidget(_icon_label(get_avatar_path(peer["account_id"], peer["avatarfull"]), 24))
                    name = QLabel(peer["personaname"])
                    name.setStyleSheet("color: white; font-family: sans-serif; font-size: 12px;")
                    row.addWidget(name)
                    row.addStretch()
                    together_wr = (peer["win"] / peer["games"] * 100) if peer["games"] else None
                    wr_label = QLabel(
                        f"{together_wr:.0f}% · {peer['games']} игр" if together_wr is not None else "н/д"
                    )
                    wr_label.setStyleSheet(
                        f"color: {_winrate_color(together_wr)}; font-family: sans-serif; font-size: 11px;"
                    )
                    row.addWidget(wr_label)
                    self._layout.addLayout(row)

        self._panel.adjustSize()
        self.adjustSize()

    def show_stats(self):
        # Re-asserted on every show, not just once in __init__ - see the
        # matching comment on OverlayWindow.show_overlay (overlay_window.py):
        # some window managers ignore an app-requested position after the
        # first map and auto-center on every later show() instead.
        self.move(*window_position.compute(self.width(), self.height()))
        self.show()

    def hide_stats(self):
        self.hide()

    def toggle(self):
        if self.isVisible():
            self.hide_stats()
        else:
            self.show_stats()
