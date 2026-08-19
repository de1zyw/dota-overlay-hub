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
from assets import get_avatar_path, get_hero_icon_path, get_item_icon_path_by_name, get_rank_icon_path
from local_hero_stats import get_hero_standings
from opendota_client import fetch_peers
from overlay_window import _GradientPanel, _icon_label, _match_history_group, _winrate_color

RANK_ICON_SIZE = 60
TOP_HERO_ICON_SIZE = 44
PEER_AVATAR_SIZE = 32
LOCAL_RECORD_HERO_ICON_SIZE = 32
RECAP_HERO_ICON_SIZE = 48
RECAP_ITEM_ICON_SIZE = 32

# Human labels for the benchmarks OpenDota returns, in display order - not
# every raw key (kills_per_min etc. are folded into the KDA line instead of
# repeated as their own percentile row).
_BENCHMARK_LABELS = [
    ("gold_per_min", "GPM"),
    ("xp_per_min", "XPM"),
    ("last_hits_per_min", "Добивания/мин"),
    ("hero_damage_per_min", "Урон/мин"),
    ("hero_healing_per_min", "Лечение/мин"),
]

# Rough, widely-known pub/competitive "good by" timings (seconds) for a
# handful of common power-spike items - NOT a real per-hero/bracket average
# (OpenDota has no ready endpoint for that; a live SQL aggregate over their
# whole match history is too slow/rate-limit-risky to run per hotkey press,
# see project notes 2026-08-19). Deliberately a short, conservative list -
# only flag items where "late" is fairly uncontroversial regardless of
# hero, skip anything too build-dependent to have one honest threshold.
_ITEM_LATE_THRESHOLD_SECONDS = {
    "blink": 600,             # 10:00
    "black_king_bar": 1200,   # 20:00
    "travel_boots": 900,      # 15:00
    "travel_boots_2": 1080,   # 18:00
    "radiance": 1080,         # 18:00
}

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
            msg.setStyleSheet("color: #aaaaaa; font-family: 'Inter'; font-size: 13px;")
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
            msg.setStyleSheet("color: #aaaaaa; font-family: 'Inter'; font-size: 13px;")
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
                "color: #e2c04c; font-family: 'Inter'; font-size: 11px; font-weight: 600;"
            )
            self._layout.addWidget(stale_msg)

        header = QHBoxLayout()
        header.addWidget(_icon_label(get_rank_icon_path(stats.rank_tier), RANK_ICON_SIZE))
        if stats.leaderboard_rank is not None:
            leaderboard_badge = QLabel(f"Топ #{stats.leaderboard_rank}")
            leaderboard_badge.setStyleSheet(
                f"color: {config.COLOR_GREEN}; font-family: 'Inter'; "
                "font-size: 11px; font-weight: bold;"
            )
            header.addWidget(leaderboard_badge)
        nickname = QLabel(stats.nickname)
        nickname.setStyleSheet(
            "color: white; font-weight: bold; font-family: 'Inter'; font-size: 20px;"
        )
        header.addWidget(nickname)
        header.addStretch()
        self._layout.addLayout(header)

        winrate_str = f"{stats.winrate:.0f}%" if stats.winrate is not None else "н/д"
        overall = QLabel(f"WR {winrate_str}  •  {stats.total_games} игр")
        overall.setStyleSheet(
            f"color: {_winrate_color(stats.winrate)}; font-family: 'Inter'; "
            "font-size: 18px; font-weight: 600;"
        )
        self._layout.addWidget(overall)

        history_label = QLabel("ПОСЛЕДНИЕ МАТЧИ")
        history_label.setStyleSheet(
            "color: #888899; font-family: 'Inter'; font-size: 11px; "
            "font-weight: bold; letter-spacing: 1px;"
        )
        self._layout.addWidget(history_label)

        self._layout.addWidget(_match_history_group(stats.recent_matches[0:5], show_kda=True))
        self._layout.addWidget(_match_history_group(stats.recent_matches[5:10], show_kda=True))

        if stats.top_heroes:
            top_heroes_label = QLabel("ТОП ГЕРОИ")
            top_heroes_label.setStyleSheet(
                "color: #888899; font-family: 'Inter'; font-size: 11px; "
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
                    _icon_label(get_hero_icon_path(hero_id), TOP_HERO_ICON_SIZE), 0, Qt.AlignmentFlag.AlignHCenter
                )
                hero_winrate = (win / games * 100) if games else None
                caption = QLabel(f"{hero_winrate:.0f}% · {games}" if hero_winrate is not None else "н/д")
                caption.setStyleSheet(
                    f"color: {_winrate_color(hero_winrate)}; font-family: 'Inter'; font-size: 10px;"
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
                    "color: #888899; font-family: 'Inter'; font-size: 11px; "
                    "font-weight: bold; letter-spacing: 1px;"
                )
                self._layout.addWidget(peers_label)
                for peer in peers:
                    row = QHBoxLayout()
                    row.addWidget(_icon_label(get_avatar_path(peer["account_id"], peer["avatarfull"]), PEER_AVATAR_SIZE))
                    name = QLabel(peer["personaname"])
                    name.setStyleSheet("color: white; font-family: 'Inter'; font-size: 12px;")
                    row.addWidget(name)
                    row.addStretch()
                    together_wr = (peer["win"] / peer["games"] * 100) if peer["games"] else None
                    wr_label = QLabel(
                        f"{together_wr:.0f}% · {peer['games']} игр" if together_wr is not None else "н/д"
                    )
                    wr_label.setStyleSheet(
                        f"color: {_winrate_color(together_wr)}; font-family: 'Inter'; font-size: 11px;"
                    )
                    row.addWidget(wr_label)
                    self._layout.addLayout(row)

            standings = get_hero_standings(stats.account_id)
            if standings:
                # Picks its own top-3 by LOCAL games played (wins+losses),
                # deliberately not tied to stats.top_heroes - that comes
                # from OpenDota's /heroes endpoint, which is empty for any
                # account with "Expose Public Match Data" off in Steam
                # (confirmed live: exactly this account). This whole
                # section exists specifically so local data still shows up
                # when OpenDota has nothing - it shouldn't need OpenDota's
                # own list to know which heroes to show.
                top_local_heroes = sorted(
                    standings.items(),
                    key=lambda item: item[1].get("wins", 0) + item[1].get("losses", 0),
                    reverse=True,
                )[:3]
                top_local_heroes = [hero_id for hero_id, entry in top_local_heroes
                                     if entry.get("wins", 0) + entry.get("losses", 0) > 0]
            if standings and top_local_heroes:
                bests_label = QLabel("ЛИЧНЫЕ РЕКОРДЫ")
                bests_label.setStyleSheet(
                    "color: #888899; font-family: 'Inter'; font-size: 11px; "
                    "font-weight: bold; letter-spacing: 1px;"
                )
                self._layout.addWidget(bests_label)
                for hero_id in top_local_heroes:
                    entry = standings.get(hero_id)
                    if not entry:
                        continue
                    row = QHBoxLayout()
                    row.addWidget(_icon_label(get_hero_icon_path(hero_id), LOCAL_RECORD_HERO_ICON_SIZE))
                    streak = entry.get("win_streak", 0)
                    streak_text = f"  •  винстрик {streak}" if streak else ""
                    text = QLabel(
                        f"рекорд: {entry.get('best_kills', 0)}/{entry.get('best_gpm', 0)} gpm{streak_text}"
                    )
                    text.setStyleSheet("color: #cccccc; font-family: 'Inter'; font-size: 11px;")
                    row.addWidget(text)
                    row.addStretch()
                    self._layout.addLayout(row)

        self._panel.adjustSize()
        self.adjustSize()

    def render_recap(self, stats):
        """Own-performance recap for one specific match (the "last match"
        hotkey) - a different shape than render_stats' profile view (one
        match's KDA/percentiles/build timing, not a match-history list), so
        it's a separate method rather than another mode bolted onto
        render_stats. stats is a PlayerStats from fetch_match_recap()."""
        self._clear_layout()

        header = QHBoxLayout()
        header.addWidget(_icon_label(get_hero_icon_path(stats.hero_id), RECAP_HERO_ICON_SIZE))
        result = QLabel("ПОБЕДА" if stats.won else "ПОРАЖЕНИЕ")
        result.setStyleSheet(
            f"color: {config.COLOR_GREEN if stats.won else config.COLOR_RED}; "
            "font-family: 'Inter'; font-size: 20px; font-weight: bold;"
        )
        header.addWidget(result)
        if stats.duration:
            mins, secs = divmod(stats.duration, 60)
            duration_label = QLabel(f"{mins}:{secs:02d}")
            duration_label.setStyleSheet("color: #888899; font-family: 'Inter'; font-size: 14px;")
            header.addWidget(duration_label)
        header.addStretch()
        self._layout.addLayout(header)

        kda = QLabel(f"{stats.kills} / {stats.deaths} / {stats.assists}  •  {stats.last_hits}/{stats.denies} лх/дн")
        kda.setStyleSheet("color: white; font-family: 'Inter'; font-size: 16px; font-weight: 600;")
        self._layout.addWidget(kda)

        if stats.benchmarks:
            bench_label = QLabel("ОТНОСИТЕЛЬНО ЭТОГО ЖЕ ГЕРОЯ (тот же бракет)")
            bench_label.setStyleSheet(
                "color: #888899; font-family: 'Inter'; font-size: 11px; "
                "font-weight: bold; letter-spacing: 1px;"
            )
            self._layout.addWidget(bench_label)
            for key, label_text in _BENCHMARK_LABELS:
                pct = stats.benchmarks.get(key)
                if pct is None:
                    continue
                row = QHBoxLayout()
                name = QLabel(label_text)
                name.setFixedWidth(110)
                name.setStyleSheet("color: #cccccc; font-family: 'Inter'; font-size: 12px;")
                row.addWidget(name)
                pct100 = pct * 100
                # "N-й перцентиль" means nothing to most players without
                # already knowing what a percentile is - "лучше/хуже X%
                # игроков" says the same thing in plain language.
                if pct100 >= 50:
                    pct_text = f"лучше {pct100:.0f}% игроков"
                else:
                    pct_text = f"хуже {100 - pct100:.0f}% игроков"
                pct_label = QLabel(pct_text)
                pct_label.setStyleSheet(
                    f"color: {_winrate_color(pct100)}; font-family: 'Inter'; "
                    "font-size: 12px; font-weight: 600;"
                )
                row.addWidget(pct_label)
                row.addStretch()
                self._layout.addLayout(row)

        if stats.tower_damage or stats.hero_healing:
            extra = QLabel(f"Урон по башням: {stats.tower_damage}  •  Лечение: {stats.hero_healing}")
            extra.setStyleSheet("color: #cccccc; font-family: 'Inter'; font-size: 11px;")
            self._layout.addWidget(extra)

        if stats.key_purchases:
            purchases_label = QLabel("КЛЮЧЕВЫЕ ПОКУПКИ")
            purchases_label.setStyleSheet(
                "color: #888899; font-family: 'Inter'; font-size: 11px; "
                "font-weight: bold; letter-spacing: 1px;"
            )
            self._layout.addWidget(purchases_label)
            for key, purchase_time in stats.key_purchases[:8]:
                row = QHBoxLayout()
                row.addWidget(_icon_label(get_item_icon_path_by_name(key), RECAP_ITEM_ICON_SIZE))
                mins, secs = divmod(max(0, purchase_time), 60)
                threshold = _ITEM_LATE_THRESHOLD_SECONDS.get(key)
                is_late = threshold is not None and purchase_time > threshold
                time_label = QLabel(f"{mins}:{secs:02d}" + ("  ⚠ позже обычного" if is_late else ""))
                time_label.setStyleSheet(
                    f"color: {'#e2704c' if is_late else '#888899'}; font-family: 'Inter'; "
                    f"font-size: 11px;{' font-weight: 600;' if is_late else ''}"
                )
                row.addWidget(time_label)
                row.addStretch()
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
