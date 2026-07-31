"""Frameless, always-on-top, translucent overlay window with a dark,
softly gradient-accented theme (pink/blue/purple glows on near-black,
inspired by a user-supplied reference palette, darkened/desaturated for
readability over live gameplay) and real hero/rank icons."""
from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui import QColor, QLinearGradient, QPainter, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

import config
from assets import get_faction_icon_path, get_hero_icon_path, get_rank_icon_path

ACCENT_PINK = QColor("#FF9CE3")
ACCENT_BLUE = QColor("#7DD3FC")
ACCENT_PURPLE = QColor("#B388FF")
# "This is you" row highlight - deliberately not blue, so it never reads as
# the same signal as the party-underline treatment below.
ACCENT_GOLD = QColor("#FFD166")
BASE_BG = QColor(10, 10, 16, 235)  # near-black, mostly opaque so text stays readable

ICON_SIZE = 28
HERO_ICON_SIZE = 32
MATCH_ICON_SIZE = 18
MATCH_ICON_BORDER = 2
MATCH_HISTORY_COUNT = 5
FACTION_ICON_SIZE = 20

# The one spacing value used everywhere icon-type elements sit next to each
# other (rank icon <-> current-pick icon <-> match-history icons <-> text,
# and between the match-history icons themselves) so the row reads as one
# consistent rhythm instead of ad-hoc per-element gaps.
ICON_GAP = 8


def _winrate_color(winrate):
    if winrate is None:
        return config.COLOR_NEUTRAL
    if winrate >= config.WINRATE_GREEN:
        return config.COLOR_GREEN
    if winrate <= config.WINRATE_RED:
        return config.COLOR_RED
    return config.COLOR_NEUTRAL


def _icon_label(path, size):
    label = QLabel()
    if path:
        pixmap = QPixmap(path)
        if not pixmap.isNull():
            label.setPixmap(
                pixmap.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio,
                               Qt.TransformationMode.SmoothTransformation)
            )
    label.setFixedSize(size, size)
    return label


def _hero_pick_icon(hero_id):
    """Current-pick hero icon, or a static local '?' placeholder (no asset
    fetch) sized to match, so the row's icon column stays aligned whether or
    not the pick is known yet."""
    if hero_id:
        return _icon_label(get_hero_icon_path(hero_id), HERO_ICON_SIZE)

    label = QLabel("?")
    label.setFixedSize(HERO_ICON_SIZE, HERO_ICON_SIZE)
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    label.setStyleSheet(
        "color: #888899; font-family: sans-serif; font-weight: bold; "
        f"font-size: {max(int(HERO_ICON_SIZE * 0.55), 10)}px; "
        "background-color: rgba(255, 255, 255, 18); "
        "border: 1px solid rgba(255, 255, 255, 50); border-radius: 5px;"
    )
    return label


def _match_history_group(recent_matches):
    """Small hero-icon strip for the last few matches, newest first, each
    ringed green (win) or red (loss) - a win is always green, never the
    background's purple accent, so the win/loss signal stays unambiguous."""
    group = QWidget()
    layout = QHBoxLayout(group)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(ICON_GAP)

    for hero_id, won in recent_matches[:MATCH_HISTORY_COUNT]:
        border_color = config.COLOR_GREEN if won else config.COLOR_RED
        inner = MATCH_ICON_SIZE - 2 * MATCH_ICON_BORDER
        label = QLabel()
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        path = get_hero_icon_path(hero_id)
        if path:
            pixmap = QPixmap(path)
            if not pixmap.isNull():
                label.setPixmap(
                    pixmap.scaled(inner, inner, Qt.AspectRatioMode.KeepAspectRatio,
                                   Qt.TransformationMode.SmoothTransformation)
                )
        label.setFixedSize(MATCH_ICON_SIZE, MATCH_ICON_SIZE)
        label.setStyleSheet(
            f"border: {MATCH_ICON_BORDER}px solid {border_color}; border-radius: 4px;"
        )
        layout.addWidget(label)

    return group


class _GradientPanel(QWidget):
    """Paints the dark base + three soft, low-opacity accent glows behind
    the content - a subtler, translucency-friendly take on the reference
    palette rather than the reference's full-opacity marketing-card look."""

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect())

        painter.setBrush(BASE_BG)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(rect, 14, 14)

        gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
        glow_pink = QColor(ACCENT_PINK)
        glow_pink.setAlpha(40)
        glow_blue = QColor(ACCENT_BLUE)
        glow_blue.setAlpha(40)
        glow_purple = QColor(ACCENT_PURPLE)
        glow_purple.setAlpha(40)
        gradient.setColorAt(0.0, glow_pink)
        gradient.setColorAt(0.5, glow_purple)
        gradient.setColorAt(1.0, glow_blue)
        painter.setBrush(gradient)
        painter.drawRoundedRect(rect, 14, 14)

        super().paintEvent(event)


def _player_row(stats, hero_id, expanded, party_account_ids):
    # A QFrame (not QWidget) is used here specifically because it lets the
    # "this is you" highlight below paint a background/border from a
    # stylesheet - plain QWidgets don't paint stylesheet backgrounds
    # without extra plumbing.
    row = QFrame()
    row.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    layout = QHBoxLayout(row)
    layout.setContentsMargins(4, 3, 4, 3)
    layout.setSpacing(ICON_GAP)

    is_you = config.MY_ACCOUNT_ID is not None and stats.account_id == config.MY_ACCOUNT_ID
    if is_you:
        # "This is you": a gold left border + faint background tint - a
        # clearly different signal from the party-underline (blue,
        # applied to the nickname text only) below, so the two never
        # look like the same highlight.
        tint = QColor(ACCENT_GOLD)
        tint.setAlpha(30)
        row.setStyleSheet(
            "QFrame { "
            f"border-left: 3px solid {ACCENT_GOLD.name()}; "
            f"background-color: rgba({tint.red()}, {tint.green()}, {tint.blue()}, {tint.alpha()}); "
            "border-radius: 4px; "
            "}"
        )

    if stats.hidden:
        label = QLabel(f"{stats.nickname} — профиль скрыт")
        label.setStyleSheet("color: #888899; font-family: sans-serif; font-size: 13px;")
        layout.addWidget(label)
        layout.addStretch()
        return row

    nickname_label = QLabel(stats.nickname)
    nickname_style = "color: white; font-family: sans-serif; font-size: 13px; font-weight: 600;"
    if stats.account_id in party_account_ids:
        # Highlight the local client's own party members (see lobby_watcher's
        # module docstring - this can never reveal enemy party groupings).
        # A distinct accent color for the underline itself keeps it readable
        # against the white nickname text rather than blending into it.
        nickname_style += f" text-decoration: underline; text-decoration-color: {ACCENT_BLUE.name()};"
    nickname_label.setStyleSheet(nickname_style)
    layout.addWidget(nickname_label)

    layout.addWidget(_icon_label(get_rank_icon_path(stats.rank_tier), ICON_SIZE))
    layout.addWidget(_hero_pick_icon(hero_id))
    layout.addWidget(_match_history_group(stats.recent_matches))

    winrate_str = f"{stats.winrate:.0f}%" if stats.winrate is not None else "н/д"
    text = f"WR {winrate_str}"
    if expanded:
        top_heroes_icons = "".join("\U0001F538" for _ in stats.top_heroes[:3])
        text += f"  |  игр: {stats.total_games}  |  {top_heroes_icons}"

    text_label = QLabel(text)
    text_label.setStyleSheet(
        f"color: {_winrate_color(stats.winrate)}; font-family: sans-serif; font-size: 13px;"
    )
    layout.addWidget(text_label)
    layout.addStretch()
    return row


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
        self._panel = _GradientPanel()
        self._layout = QVBoxLayout(self._panel)
        self._layout.setContentsMargins(14, 12, 14, 12)
        self._layout.setSpacing(4)

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

    def _section_header(self, text, team):
        """RADIANT/DIRE header: faction icon (real emblem if fetched, else
        nothing - text alone still reads fine) beside the label text, tinted
        with the same green/red convention used for win/loss elsewhere."""
        header = QWidget()
        layout = QHBoxLayout(header)
        layout.setContentsMargins(0, 6, 0, 4)
        layout.setSpacing(ICON_GAP)

        icon_path = get_faction_icon_path(team)
        if icon_path:
            layout.addWidget(_icon_label(icon_path, FACTION_ICON_SIZE))

        color = config.COLOR_GREEN if team == "radiant" else config.COLOR_RED
        label = QLabel(text)
        label.setStyleSheet(
            f"color: {color}; font-weight: bold; font-family: sans-serif; "
            "font-size: 12px; letter-spacing: 2px;"
        )
        layout.addWidget(label)
        layout.addStretch()
        return header

    def _section_divider(self):
        """Thin horizontal rule marking the boundary between the Radiant and
        Dire blocks - a bit more visual separation than spacing alone."""
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFixedHeight(1)
        line.setStyleSheet("background-color: rgba(255, 255, 255, 40); border: none;")
        return line

    def render_lobby(self, radiant, dire, current_picks, party_account_ids):
        self._clear_layout()

        self._layout.addWidget(self._section_header("RADIANT", "radiant"))
        for stats in radiant:
            self._layout.addWidget(
                _player_row(stats, current_picks.get(stats.account_id), self._expanded, party_account_ids)
            )

        self._layout.addWidget(self._section_divider())

        self._layout.addWidget(self._section_header("DIRE", "dire"))
        for stats in dire:
            self._layout.addWidget(
                _player_row(stats, current_picks.get(stats.account_id), self._expanded, party_account_ids)
            )

        self._panel.adjustSize()
        self.adjustSize()

    def show_overlay(self):
        self.show()

    def hide_overlay(self):
        self.hide()

    def toggle_expanded(self):
        self._expanded = not self._expanded


if __name__ == "__main__":
    import sys

    from opendota_client import fetch_player_stats

    app = QApplication(sys.argv)
    window = OverlayWindow()

    radiant = [fetch_player_stats(111620041)]
    dire = []
    window.render_lobby(radiant, dire, {111620041: 1}, {111620041})
    window.show_overlay()

    sys.exit(app.exec())
