"""Frameless, always-on-top, translucent overlay window with a dark,
softly gradient-accented theme (pink/blue/purple glows on near-black,
inspired by a user-supplied reference palette, darkened/desaturated for
readability over live gameplay) and real hero/rank icons."""
from PyQt6.QtCore import Qt, QPointF, QRectF
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPixmap, QRadialGradient
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

import config
import error_codes
import window_position
# `assets` is deliberately NOT imported here at module level - it imports
# `requests` (and, through opendota_client, its Session/throttle setup),
# measured via -X importtime at ~55-60ms - and this file's _GradientPanel
# is imported by launcher.py for the HUB window's own background panel,
# so a top-level import here meant every hub startup paid that cost
# before the hub window even showed, regardless of whether any Dota match
# (the only time these icon lookups actually run) was ever seen. Each call
# site below does its own local `import assets` instead - cheap
# (sys.modules-cached) after the first real call, first paid only once an
# icon actually needs fetching.

ACCENT_PINK = QColor("#FF9CE3")
ACCENT_BLUE = QColor("#7DD3FC")
# Purple (#B388FF) is no longer a standalone constant - it now emerges
# naturally where the pink and blue glows below overlap, matching the
# reference image, rather than being painted as its own gradient stop.
# "This is you" row highlight - deliberately not blue, so it never reads as
# the same signal as the party-underline treatment below.
ACCENT_GOLD = QColor("#FFD166")
# Task 18: alpha raised from 235 - per user feedback the panel read as too
# see-through against a bright game background to read comfortably; 250/255
# is close to solid while leaving a hint of translucency at the very edge of
# perceptibility, still recognizable as an overlay rather than a fully
# opaque window.
# Matches the user's original reference image ("AURA" card, 2026-08-02
# redesign pass) more literally than the old base - near-pure black rather
# than a dark blue-grey, since the reference's glows sit on true black with
# large black corners, not a lit-up panel edge to edge.
BASE_BG = QColor(4, 4, 6, 250)

ICON_SIZE = 40
HERO_ICON_SIZE = 38
MATCH_ICON_SIZE = 26
MATCH_ICON_BORDER = 2
MATCH_HISTORY_COUNT = 5
FACTION_ICON_SIZE = 28
ITEM_ICON_SIZE = 36

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


# Task 18: A/B-compared Qt.TransformationMode.SmoothTransformation against
# FastTransformation at the actual rendered sizes (28px rank icons from
# 256px source, 18px match-history icons from 32px source, 20px faction
# icons from 128px source) via real screenshots. At every one of these
# large downscale ratios, SmoothTransformation blurred the flat-color,
# hard-edged Dota icon art into a muddy wash, while FastTransformation
# (nearest-neighbor) kept edges and color boundaries crisp - the opposite
# of what "smooth" implies for photographic content, but correct for this
# specific pixel-art-style asset style. Used everywhere icons are scaled.
def _icon_label(path, size):
    label = QLabel()
    if path:
        pixmap = QPixmap(path)
        if not pixmap.isNull():
            label.setPixmap(
                pixmap.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio,
                               Qt.TransformationMode.FastTransformation)
            )
    label.setFixedSize(size, size)
    return label


def _hero_pick_icon(hero_id):
    """Current-pick hero icon, or a static local '?' placeholder (no asset
    fetch) sized to match, so the row's icon column stays aligned whether or
    not the pick is known yet."""
    if hero_id:
        import assets
        return _icon_label(assets.get_hero_icon_path(hero_id), HERO_ICON_SIZE)

    label = QLabel("?")
    label.setFixedSize(HERO_ICON_SIZE, HERO_ICON_SIZE)
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    label.setStyleSheet(
        "color: #888899; font-family: 'Inter'; font-weight: bold; "
        f"font-size: {max(int(HERO_ICON_SIZE * 0.55), 10)}px; "
        "background-color: rgba(255, 255, 255, 18); "
        "border: 1px solid rgba(255, 255, 255, 50); border-radius: 5px;"
    )
    return label


def _match_history_group(recent_matches, show_kda=False):
    """Small hero-icon strip for the last few matches, newest first, each
    ringed green (win) or red (loss) - a win is always green, never the
    background's purple accent, so the win/loss signal stays unambiguous.
    show_kda=True (player_stats_window.py only - the compact draft row has
    no room for it) adds a small "K/D/A" caption under each icon."""
    import assets
    group = QWidget()
    layout = QHBoxLayout(group)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(ICON_GAP)

    for match in recent_matches[:MATCH_HISTORY_COUNT]:
        border_color = config.COLOR_GREEN if match.won else config.COLOR_RED
        inner = MATCH_ICON_SIZE - 2 * MATCH_ICON_BORDER
        label = QLabel()
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        path = assets.get_hero_icon_path(match.hero_id)
        if path:
            pixmap = QPixmap(path)
            if not pixmap.isNull():
                label.setPixmap(
                    pixmap.scaled(inner, inner, Qt.AspectRatioMode.KeepAspectRatio,
                                   Qt.TransformationMode.FastTransformation)
                )
        label.setFixedSize(MATCH_ICON_SIZE, MATCH_ICON_SIZE)
        label.setStyleSheet(
            f"border: {MATCH_ICON_BORDER}px solid {border_color}; border-radius: 4px;"
        )

        if not show_kda:
            layout.addWidget(label)
            continue

        # Icon + caption stacked - a plain QLabel can't hold both, and the
        # caption is wider than the 18px icon, so this is a small column,
        # not just the bare icon. Qt sizes each column to its widest child
        # (the caption text) automatically - no manual width math needed.
        entry = QWidget()
        entry_layout = QVBoxLayout(entry)
        entry_layout.setContentsMargins(0, 0, 0, 0)
        entry_layout.setSpacing(2)
        entry_layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        entry_layout.addWidget(label, 0, Qt.AlignmentFlag.AlignHCenter)
        kda = QLabel(f"{match.kills}/{match.deaths}/{match.assists}")
        kda.setStyleSheet("color: #aaaaaa; font-family: 'Inter'; font-size: 9px;")
        kda.setAlignment(Qt.AlignmentFlag.AlignCenter)
        entry_layout.addWidget(kda)
        layout.addWidget(entry)

    return group


def _rounded_rect_path(rect, rx, ry):
    path = QPainterPath()
    path.addRoundedRect(rect, rx, ry)
    return path


def _glow(center, radius, color, peak_alpha):
    """A soft radial light patch - full color at the center, fading to
    fully transparent by its edge, so overlapping glows blend into each
    other (e.g. pink + blue -> purple in between) instead of showing a
    hard-edged circle."""
    gradient = QRadialGradient(center, radius)
    core = QColor(color)
    core.setAlpha(peak_alpha)
    edge = QColor(color)
    edge.setAlpha(0)
    gradient.setColorAt(0.0, core)
    gradient.setColorAt(1.0, edge)
    return gradient


class _GradientPanel(QWidget):
    """Matches the user's original reference image ("AURA" card): near-black
    base with two large, soft, blurred glow patches - pink toward the top
    left, blue toward the right - that overlap in the middle into purple,
    rather than a single smooth gradient wash spanning the whole panel.
    Most of the panel (corners especially) stays close to pure black,
    exactly as in the reference, with the glows read as distinct light
    sources rather than a tinted background."""

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect())

        painter.setBrush(BASE_BG)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(rect, 14, 14)

        diagonal = (rect.width() ** 2 + rect.height() ** 2) ** 0.5
        painter.setClipPath(_rounded_rect_path(rect, 14, 14))

        painter.setBrush(_glow(
            QPointF(rect.left() + rect.width() * 0.18, rect.top() + rect.height() * 0.2),
            diagonal * 0.55, ACCENT_PINK, 70,
        ))
        painter.drawRect(rect)

        painter.setBrush(_glow(
            QPointF(rect.right() - rect.width() * 0.15, rect.top() + rect.height() * 0.55),
            diagonal * 0.55, ACCENT_BLUE, 70,
        ))
        painter.drawRect(rect)

        super().paintEvent(event)


def _player_row(stats, hero_id, expanded, party_account_ids):
    import assets
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
        #
        # Scoped to an objectName, not a bare "QFrame { ... }" type
        # selector - a type selector cascades down to every matching
        # descendant Qt finds in the tree, not just the widget it was set
        # on, which visibly gave every child label its own separate gold
        # bracket+background instead of one shared highlight across the
        # whole row (confirmed live via an isolated render with zero
        # children beyond the nickname/hero-icon placeholder - same
        # per-widget cascade already documented and fixed this same way
        # for _OverlayCard in launcher.py).
        tint = QColor(ACCENT_GOLD)
        tint.setAlpha(30)
        row.setObjectName("isYouRow")
        row.setStyleSheet(
            "QFrame#isYouRow { "
            f"border-left: 3px solid {ACCENT_GOLD.name()}; "
            f"background-color: rgba({tint.red()}, {tint.green()}, {tint.blue()}, {tint.alpha()}); "
            "border-radius: 4px; "
            "}"
        )

    if stats.hidden:
        # error_reason set means OpenDota itself is unavailable right now
        # (network/rate-limit/their outage) - worded differently from a
        # genuinely private profile so the row doesn't read as "this
        # player is hiding something" when it's actually just our data
        # source being briefly down.
        if stats.error_reason:
            code = stats.error_code
            code_tag = (
                error_codes.http_tag(code) if code in range(100, 600) else error_codes.tag(code)
            ) if code is not None else ""
            suffix = f"OpenDota недоступен {code_tag}".strip()
        else:
            suffix = "профиль скрыт"
        label = QLabel(f"{stats.nickname} — {suffix}")
        label.setStyleSheet("color: #888899; font-family: 'Inter'; font-size: 13px;")
        # Fixed to the same height as the icon-bearing rows below (driven by
        # HERO_ICON_SIZE, the tallest fixed-size widget in a normal row) so a
        # run of hidden-profile rows doesn't collapse to a shorter row height
        # than its neighbors - without this the list's vertical rhythm was
        # visibly uneven, icon rows noticeably taller than hidden-profile
        # ones sitting right next to them.
        label.setFixedHeight(HERO_ICON_SIZE)
        layout.addWidget(label)
        layout.addStretch()
        return row

    # stale: a live re-fetch failed but a previous successful fetch for this
    # account exists, so real (if slightly old) numbers are shown instead of
    # blanking the row - the "⚠" is the only hint of that trade-off here;
    # the full "updated N min ago" explanation lives in player_stats_window,
    # which has room for it and isn't on a tight draft-timer clock.
    nickname_text = f"⚠ {stats.nickname}" if stats.stale else stats.nickname
    nickname_label = QLabel(nickname_text)
    nickname_style = "color: white; font-family: 'Inter'; font-size: 13px; font-weight: 600;"
    if stats.account_id in party_account_ids:
        # Highlight the local client's own party members (see lobby_watcher's
        # module docstring - this can never reveal enemy party groupings).
        # A distinct accent color for the underline itself keeps it readable
        # against the white nickname text rather than blending into it.
        nickname_style += f" text-decoration: underline; text-decoration-color: {ACCENT_BLUE.name()};"
    nickname_label.setStyleSheet(nickname_style)
    layout.addWidget(nickname_label)

    layout.addWidget(_icon_label(assets.get_rank_icon_path(stats.rank_tier), ICON_SIZE))
    layout.addWidget(_hero_pick_icon(hero_id))
    layout.addWidget(_match_history_group(stats.recent_matches))

    winrate_str = f"{stats.winrate:.0f}%" if stats.winrate is not None else "н/д"
    text = f"WR {winrate_str}"
    if expanded:
        top_heroes_icons = "".join("\U0001F538" for _ in stats.top_heroes[:3])
        text += f"  |  игр: {stats.total_games}  |  {top_heroes_icons}"

    text_label = QLabel(text)
    text_label.setStyleSheet(
        f"color: {_winrate_color(stats.winrate)}; font-family: 'Inter'; font-size: 13px;"
    )
    layout.addWidget(text_label)
    layout.addStretch()

    if not (expanded and any(stats.items)):
        return row

    # Item build (last-match recap only - stats.items is empty for
    # self-stats/profile-lookup/live-draft, which aren't about one
    # specific match) - wraps the already-built row instead of
    # restructuring it internally, so the row's own styling (the "is
    # you" gold border above) is untouched.
    container = QWidget()
    container.setStyleSheet("background: transparent;")
    outer = QVBoxLayout(container)
    outer.setContentsMargins(0, 0, 0, 0)
    outer.setSpacing(2)
    outer.addWidget(row)

    items_row = QWidget()
    items_row.setStyleSheet("background: transparent;")
    items_layout = QHBoxLayout(items_row)
    items_layout.setContentsMargins(8, 0, 4, 4)
    items_layout.setSpacing(3)
    for item_id in stats.items:
        icon_path = assets.get_item_icon_path(item_id)
        if icon_path:
            items_layout.addWidget(_icon_label(icon_path, ITEM_ICON_SIZE))
    items_layout.addStretch()
    outer.addWidget(items_row)

    return container


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

        self.move(*window_position.compute(self.width(), self.height()))

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
        import assets
        header = QWidget()
        layout = QHBoxLayout(header)
        layout.setContentsMargins(0, 6, 0, 4)
        layout.setSpacing(ICON_GAP)

        icon_path = assets.get_faction_icon_path(team)
        if icon_path:
            layout.addWidget(_icon_label(icon_path, FACTION_ICON_SIZE))

        color = config.COLOR_GREEN if team == "radiant" else config.COLOR_RED
        label = QLabel(text)
        label.setStyleSheet(
            f"color: {color}; font-weight: bold; font-family: 'Inter'; "
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
        # Re-asserted on every show, not just once in __init__ - some
        # window managers only honor an app-requested position on the
        # window's first-ever map, then auto-center it (or otherwise
        # reposition it) on every later show() regardless of move() calls
        # made while it was hidden. Calling move() again right before
        # show() forces the position back every time instead of once.
        # Uses the current (already rendered/adjustSize()'d) width/height,
        # not __init__'s - the user's chosen corner/center can put this
        # anywhere on screen, so a stale size would visibly misplace it.
        self.move(*window_position.compute(self.width(), self.height()))
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
