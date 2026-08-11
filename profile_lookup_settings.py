"""Persisted screen region for profile-lookup OCR, calibrated once by the
user via region_calibrator.py. load() never raises - returns None if no
region has been calibrated yet (the feature simply can't do anything
useful until then, same as any other unmet prerequisite in this app).
save() never raises either - a failed write just means the calibration
didn't persist."""
import json
import os

import platform_utils

SETTINGS_PATH = os.path.join(platform_utils.data_dir(), "profile_lookup_settings.json")


def load():
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return None
        if any(data.get(key) is None for key in ("x", "y", "width", "height")):
            return None
        return {key: data[key] for key in ("x", "y", "width", "height")}
    except (OSError, json.JSONDecodeError):
        return None


def save(region):
    try:
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(region, f, indent=2)
        return True
    except OSError:
        return False
