"""Discord Rich Presence - shows a small "playing this" card on the
user's Discord profile while the hub is running. Best-effort everywhere:
Rich Presence needs the Discord desktop client running locally (a local
IPC socket, not a real network API) and a Client ID from the user's own
Discord Developer account (see discord_presence_settings.py's docstring
for why this app can't obtain one on its own) - any failure here
(pypresence not installed, Discord closed, not configured/enabled) just
means presence silently doesn't show, never a crash or a blocked UI.
Every public function runs the actual IPC call on a throwaway daemon
thread - it's normally fast (local socket), but this app has been bitten
once already this session by a "should be fast" network-ish call blocking
the main thread (see launcher.py's own history), not repeating that here."""
import threading
import time

import discord_presence_settings

try:
    from pypresence import Presence
except ImportError:
    Presence = None

_lock = threading.Lock()
_client = None
_connected_client_id = None
_start_time = int(time.time())


def available():
    return Presence is not None


def _get_client(client_id):
    global _client, _connected_client_id
    if _client is not None and _connected_client_id == client_id:
        return _client
    if _client is not None:
        try:
            _client.close()
        except Exception:  # noqa: BLE001 - best-effort teardown
            pass
        _client = None
    try:
        client = Presence(client_id)
        client.connect()
    except Exception:  # noqa: BLE001 - Discord not running, bad ID, etc.
        return None
    _client = client
    _connected_client_id = client_id
    return _client


def _set(details, state):
    if Presence is None:
        return
    settings = discord_presence_settings.load()
    if not settings["enabled"] or not discord_presence_settings.is_valid_client_id(settings["client_id"]):
        return
    with _lock:
        client = _get_client(settings["client_id"])
        if client is None:
            return
        try:
            client.update(details=details, state=state, start=_start_time)
        except Exception:  # noqa: BLE001
            global _client
            _client = None  # force a reconnect attempt next time


def update_async(details, state):
    threading.Thread(target=_set, args=(details, state), daemon=True).start()


def _clear():
    with _lock:
        if _client is not None:
            try:
                _client.clear()
            except Exception:  # noqa: BLE001
                pass


def clear_async():
    threading.Thread(target=_clear, daemon=True).start()
