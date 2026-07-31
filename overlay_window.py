"""Frameless, always-on-top, translucent overlay window.
Teams stacked top-to-bottom, one row per player. Extra stats collapse
behind `.toggle_expanded()`. No hero icon images in this pass - text + color."""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

import config

RANK_TIERS = {
    1: "Herald", 2: "Guardian", 3: "Crusader", 4: "Archon",
    5: "Legend", 6: "Ancient", 7: "Divine", 8: "Immortal",
}


def _format_rank(rank_tier):
    if not rank_tier:
        return "без ранга"
    tier = rank_tier // 10
    stars = rank_tier % 10
    name = RANK_TIERS.get(tier, "?")
    if tier == 8:
        return "Immortal"
    return f"{name} {stars}"


def _winrate_color(winrate):
    if winrate is None:
        return config.COLOR_NEUTRAL
    if winrate >= config.WINRATE_GREEN:
        return config.COLOR_GREEN
    if winrate <= config.WINRATE_RED:
        return config.COLOR_RED
    return config.COLOR_NEUTRAL


def _player_row_text(stats, hero_id, expanded):
    if stats.hidden:
        return f"{stats.nickname} — профиль скрыт"

    winrate_str = f"{stats.winrate:.0f}%" if stats.winrate is not None else "н/д"
    current = f" | пик: {hero_id}" if hero_id else ""
    rank_str = _format_rank(stats.rank_tier)
    base = f"{stats.nickname} ({rank_str}) | WR {winrate_str} | {stats.last10}{current}"
    if expanded:
        base += f" | игр: {stats.total_games} | топ: {stats.top_heroes} | {stats.dotabuff_url}"
    return base


class OverlayWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowOpacity(config.WINDOW_OPACITY)

        self._expanded = False
        self._layout = QVBoxLayout(self)
        self.setLayout(self._layout)
        self.move(config.WINDOW_MARGIN_PX, config.WINDOW_MARGIN_PX)

    def _clear_layout(self):
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

    def render_lobby(self, radiant, dire, current_picks, banned_heroes):
        self._clear_layout()

        header = QLabel("RADIANT")
        header.setStyleSheet("color: white; font-weight: bold;")
        self._layout.addWidget(header)
        for stats in radiant:
            hero_id = current_picks.get(stats.account_id)
            label = QLabel(_player_row_text(stats, hero_id, self._expanded))
            label.setStyleSheet(f"color: {_winrate_color(stats.winrate)};")
            self._layout.addWidget(label)

        header = QLabel("DIRE")
        header.setStyleSheet("color: white; font-weight: bold;")
        self._layout.addWidget(header)
        for stats in dire:
            hero_id = current_picks.get(stats.account_id)
            label = QLabel(_player_row_text(stats, hero_id, self._expanded))
            label.setStyleSheet(f"color: {_winrate_color(stats.winrate)};")
            self._layout.addWidget(label)

        bans_header = QLabel("BEST BANS (pro scene)")
        bans_header.setStyleSheet("color: white; font-weight: bold;")
        self._layout.addWidget(bans_header)
        for name, count in banned_heroes:
            self._layout.addWidget(QLabel(f"{name}: {count}"))

        self.adjustSize()

    def show_overlay(self):
        self.show()

    def hide_overlay(self):
        self.hide()

    def toggle_expanded(self):
        self._expanded = not self._expanded


if __name__ == "__main__":
    import sys

    from meta_client import fetch_top_banned_heroes
    from opendota_client import fetch_player_stats

    app = QApplication(sys.argv)
    window = OverlayWindow()

    radiant = [fetch_player_stats(111620041)]
    dire = []
    window.render_lobby(radiant, dire, {111620041: None}, fetch_top_banned_heroes(3))
    window.show_overlay()

    sys.exit(app.exec())
