"""Persisted Discord Rich Presence preference - off by default (no Client
ID configured means no-op everywhere in discord_presence.py, never an
error). A Discord Application Client ID is required by Discord's own RPC
protocol and can only be created by the user themselves (a free, few-click
signup at discord.com/developers/applications, tied to their own Discord
account) - not something this app can obtain on its own."""
import json
import os
import re

SETTINGS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "discord_presence_settings.json")

_CLIENT_ID_RE = re.compile(r"^\d{15,25}$")  # Discord snowflake IDs are 17-19 digits currently


def is_valid_client_id(client_id):
    return bool(_CLIENT_ID_RE.match(client_id or ""))


def load():
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {
            "enabled": bool(data.get("enabled")),
            "client_id": data.get("client_id") or "",
        }
    except (OSError, json.JSONDecodeError):
        return {"enabled": False, "client_id": ""}


def save(enabled, client_id):
    try:
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump({"enabled": bool(enabled), "client_id": client_id or ""}, f, indent=2)
        return True
    except OSError:
        return False
