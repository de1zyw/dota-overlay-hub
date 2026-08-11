"""Persisted overlay position preference - a screen corner or center.
load() never raises - a missing/corrupt settings file falls back to the
top-left default. save() never raises either - a failed write just means
the change didn't persist."""
import json
import os

import platform_utils

SETTINGS_PATH = os.path.join(platform_utils.data_dir(), "overlay_position_settings.json")

DEFAULT_POSITION = "top_left"
POSITIONS = ("top_left", "top_right", "bottom_left", "bottom_right", "center")
POSITION_LABELS = {
    "top_left": "Верхний левый угол",
    "top_right": "Верхний правый угол",
    "bottom_left": "Нижний левый угол",
    "bottom_right": "Нижний правый угол",
    "center": "По центру экрана",
}


def load():
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        position = data.get("position")
        if position in POSITIONS:
            return position
    except (OSError, json.JSONDecodeError):
        pass
    return DEFAULT_POSITION


def save(position):
    if position not in POSITIONS:
        return False
    try:
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump({"position": position}, f, indent=2)
        return True
    except OSError:
        return False
