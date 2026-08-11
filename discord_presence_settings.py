"""Persisted Discord Rich Presence preference - off by default (opt-in
checkbox), but no longer needs the user to create their own Discord
Application. A Discord RPC Client ID doesn't have to be per-user - it's
just an identifier for what app is showing the presence card, and
Discord's local IPC has no issue with many machines using the same one
(this is how most distributed Rich-Presence-enabled tools work, e.g.
game mod menus with a single shared Client ID baked in). DEFAULT_CLIENT_ID
below is this project's own Discord Application - a manual override is
still supported (advanced/self-hosted use) but isn't required anymore."""
import json
import os

import platform_utils
import re

SETTINGS_PATH = os.path.join(platform_utils.data_dir(), "discord_presence_settings.json")

_CLIENT_ID_RE = re.compile(r"^\d{15,25}$")  # Discord snowflake IDs are 17-19 digits currently

DEFAULT_CLIENT_ID = "1536751694141198376"


def is_valid_client_id(client_id):
    return bool(_CLIENT_ID_RE.match(client_id or ""))


def load():
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {
            "enabled": bool(data.get("enabled")),
            "client_id": data.get("client_id") or DEFAULT_CLIENT_ID,
        }
    except (OSError, json.JSONDecodeError):
        return {"enabled": False, "client_id": DEFAULT_CLIENT_ID}


def save(enabled, client_id):
    try:
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump({"enabled": bool(enabled), "client_id": client_id or DEFAULT_CLIENT_ID}, f, indent=2)
        return True
    except OSError:
        return False
