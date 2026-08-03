"""Computes the (x, y) top-left position for a window given its current
size, the user's configured corner/center preference
(overlay_position_settings.py), and the real screen size - re-run on every
show() (see the matching comment in overlay_window.py/player_stats_window.py
for why a one-time move() isn't enough on some window managers)."""
from PyQt6.QtGui import QGuiApplication

import config
import overlay_position_settings

_FALLBACK_SCREEN_SIZE = (1920, 1080)


def compute(window_width, window_height):
    position = overlay_position_settings.load()
    margin = config.WINDOW_MARGIN_PX

    screen = QGuiApplication.primaryScreen()
    geo = screen.availableGeometry() if screen else None
    screen_w, screen_h = (geo.width(), geo.height()) if geo else _FALLBACK_SCREEN_SIZE

    if position == "top_right":
        return screen_w - window_width - margin, margin
    if position == "bottom_left":
        return margin, screen_h - window_height - margin
    if position == "bottom_right":
        return screen_w - window_width - margin, screen_h - window_height - margin
    if position == "center":
        return (screen_w - window_width) // 2, (screen_h - window_height) // 2
    return margin, margin  # top_left, and the fallback for an unknown value
