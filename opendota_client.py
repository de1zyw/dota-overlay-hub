"""Thin OpenDota client - throttled, cached, retrying.
Adapted from ~/dota_stats_bot/opendota_api.py, trimmed to what the overlay needs."""
import random
import threading
import time
from dataclasses import dataclass, field

import requests

BASE_URL = "https://api.opendota.com/api"
MIN_REQUEST_INTERVAL = 1.05
MAX_RETRIES = 4
RETRYABLE_STATUSES = {429, 500, 502, 503, 504}

_last_request_at = 0.0
_throttle_lock = threading.Lock()
_cache = {}
_cache_lock = threading.Lock()


class OpenDotaError(Exception):
    pass


def _throttle():
    global _last_request_at
    with _throttle_lock:
        wait = _last_request_at + MIN_REQUEST_INTERVAL - time.time()
        if wait > 0:
            time.sleep(wait)
        _last_request_at = time.time()


def _get(endpoint, params=None, timeout=(5, 15)):
    last_error = "unknown error"
    for attempt in range(MAX_RETRIES):
        _throttle()
        try:
            resp = requests.get(f"{BASE_URL}{endpoint}", params=params, timeout=timeout)
        except requests.exceptions.RequestException as e:
            last_error = str(e)
            time.sleep((2 ** attempt) + random.uniform(0, 0.5))
            continue
        if resp.status_code in RETRYABLE_STATUSES:
            last_error = f"HTTP {resp.status_code}"
            if attempt < MAX_RETRIES - 1:
                time.sleep((2 ** attempt) + random.uniform(0, 0.5))
                continue
        try:
            resp.raise_for_status()
        except requests.exceptions.RequestException as e:
            raise OpenDotaError(f"OpenDota request failed: {e}")
        return resp.json()
    raise OpenDotaError(f"OpenDota unreachable after {MAX_RETRIES} attempts ({last_error})")


def _cached_get(endpoint, params=None, ttl=30):
    key = (endpoint, tuple(sorted((params or {}).items())))
    with _cache_lock:
        entry = _cache.get(key)
        if entry and entry[0] > time.time():
            return entry[1]
    data = _get(endpoint, params)
    with _cache_lock:
        _cache[key] = (time.time() + ttl, data)
    return data


@dataclass
class PlayerStats:
    account_id: int
    nickname: str
    hidden: bool
    rank_tier: int = None
    total_games: int = 0
    winrate: float = None
    recent_matches: list = field(default_factory=list)  # [(hero_id, won: bool), ...], newest first, max 10
    top_heroes: list = field(default_factory=list)
    dotabuff_url: str = ""


def fetch_player_stats(account_id):
    dotabuff_url = f"https://www.dotabuff.com/players/{account_id}"

    try:
        profile = _cached_get(f"/players/{account_id}", ttl=30)
    except OpenDotaError:
        return PlayerStats(account_id=account_id, nickname=f"[{account_id}]", hidden=True,
                            dotabuff_url=dotabuff_url)

    profile_info = profile.get("profile") or {}
    nickname = profile_info.get("personaname") or f"[{account_id}]"

    try:
        wl = _cached_get(f"/players/{account_id}/wl", ttl=30)
    except OpenDotaError:
        wl = {}
    wins, losses = wl.get("win", 0), wl.get("lose", 0)
    total_games = wins + losses
    winrate = (wins / total_games * 100) if total_games else None
    hidden = total_games == 0 and not profile_info.get("personaname")

    try:
        recent = _cached_get(f"/players/{account_id}/recentMatches", ttl=20) or []
    except OpenDotaError:
        recent = []
    recent_matches = [
        (m.get("hero_id"), m.get("radiant_win") == (m.get("player_slot", 0) < 128))
        for m in recent[:10]
    ]

    try:
        heroes = _cached_get(f"/players/{account_id}/heroes", ttl=60) or []
    except OpenDotaError:
        heroes = []
    top_heroes = [h["hero_id"] for h in heroes if h.get("games", 0) > 0][:3]

    return PlayerStats(
        account_id=account_id, nickname=nickname, hidden=hidden,
        rank_tier=profile.get("rank_tier"), total_games=total_games, winrate=winrate,
        recent_matches=recent_matches, top_heroes=top_heroes, dotabuff_url=dotabuff_url,
    )
