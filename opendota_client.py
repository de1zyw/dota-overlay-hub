"""Thin OpenDota client - throttled, cached, retrying.
Adapted from ~/dota_stats_bot/opendota_api.py, trimmed to what the overlay needs."""
import collections
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace

import requests

BASE_URL = "https://api.opendota.com/api"
# OpenDota's unauthenticated tier is a per-minute budget (~60/min), not a
# hard "never less than N seconds apart" rule - the previous flat
# MIN_REQUEST_INTERVAL=1.05s gate serialized EVERY request globally
# (regardless of which thread made it), so fetching one player's 4
# endpoints, let alone a 10-player draft roster's 40, took 1.05s PER
# REQUEST no matter how much the callers had already parallelized. A
# sliding 60s window allows a burst up to the real budget, staying under
# it on average, without punishing a single hotkey press that only needs
# a handful of requests right now.
_MAX_REQUESTS_PER_WINDOW = 55
_WINDOW_SECONDS = 60.0
MAX_RETRIES = 4
RETRYABLE_STATUSES = {429, 500, 502, 503, 504}

_request_times = collections.deque()
_throttle_lock = threading.Lock()
_cache = {}
_cache_lock = threading.Lock()
# Separate from _cache above (which is short-TTL, for de-duplicating bursts
# of identical requests): this remembers the LAST SUCCESSFULLY BUILT
# PlayerStats per account_id indefinitely, so a transient OpenDota outage or
# rate-limit hit can fall back to "slightly stale but real" data instead of
# a blank "профиль скрыт" - which used to be indistinguishable from a
# genuinely private profile and left the user guessing whether the tool was
# broken or the player's privacy settings were the cause.
_stats_fallback_cache = {}
_stats_fallback_lock = threading.Lock()
# Shared connection pool - plain requests.get() opens a fresh TCP+TLS
# connection per call; reusing a Session lets keep-alive skip that
# handshake on every request after the first to the same host, which
# matters a lot once requests are actually running concurrently instead
# of one-per-second.
_session = requests.Session()
# Fetching one player's stats fans out to 4 independent endpoints
# (profile/wl/recentMatches/heroes) - shared so a draft roster's 10
# concurrent players don't each spin up their own pool of threads on top
# of app.py's own per-player executor.
#
# Deliberately small, confirmed the hard way: max_workers=40 (matching the
# theoretical worst case of 10 players x 4 endpoints at once) made a
# 10-player fetch take 61s - WORSE than the original serial version. A
# sliding per-minute budget alone wasn't the whole story; OpenDota's free
# tier also appears to punish an instantaneous burst specifically (lots of
# near-simultaneous 429s -> every one of them exponential-backing-off).
# This pool size is the actual concurrency cap, since it's shared across
# every fetch_player_stats() call regardless of how many players app.py
# is fetching at once - 6 concurrent requests was fast for a single
# player (4 requests, well under this cap) and didn't retrigger the burst
# penalty for a full 10-player roster in testing.
_endpoint_executor = ThreadPoolExecutor(max_workers=6, thread_name_prefix="opendota-endpoint")


class OpenDotaError(Exception):
    """reason is one of "network" (DNS/timeout/connection - the user's own
    internet), "rate_limited" (OpenDota's free-tier 429), "server_error"
    (OpenDota 5xx - their outage, not ours), "invalid_json" (malformed
    body), or "http_error" (any other non-2xx, e.g. a genuine 404). Callers
    use this to show a message that matches what's actually wrong instead
    of one generic "unavailable" for every case."""

    def __init__(self, message, reason="http_error"):
        super().__init__(message)
        self.reason = reason


def _throttle():
    while True:
        with _throttle_lock:
            now = time.time()
            while _request_times and now - _request_times[0] > _WINDOW_SECONDS:
                _request_times.popleft()
            if len(_request_times) < _MAX_REQUESTS_PER_WINDOW:
                _request_times.append(now)
                return
            wait = _WINDOW_SECONDS - (now - _request_times[0]) + 0.05
        time.sleep(wait)


def _get(endpoint, params=None, timeout=(5, 15)):
    last_error = "unknown error"
    last_reason = "network"
    for attempt in range(MAX_RETRIES):
        _throttle()
        try:
            resp = _session.get(f"{BASE_URL}{endpoint}", params=params, timeout=timeout)
        except requests.exceptions.RequestException as e:
            last_error = str(e)
            last_reason = "network"
            time.sleep((2 ** attempt) + random.uniform(0, 0.5))
            continue
        if resp.status_code in RETRYABLE_STATUSES:
            last_error = f"HTTP {resp.status_code}"
            last_reason = "rate_limited" if resp.status_code == 429 else "server_error"
            if attempt < MAX_RETRIES - 1:
                time.sleep((2 ** attempt) + random.uniform(0, 0.5))
                continue
        try:
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.RequestException as e:
            raise OpenDotaError(f"OpenDota request failed: {e}", reason=last_reason)
        except ValueError as e:
            # resp.json() on a 200 with a malformed/non-JSON body (CDN
            # error page, truncated response under rate-limit, etc.) - a
            # JSONDecodeError here used to escape this function entirely,
            # bypassing every caller's OpenDotaError->empty-result fallback.
            raise OpenDotaError(f"OpenDota returned invalid JSON: {e}", reason="invalid_json")
    raise OpenDotaError(f"OpenDota unreachable after {MAX_RETRIES} attempts ({last_error})", reason=last_reason)


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


def search_players(name):
    """None means the search itself failed (network/rate-limit - OpenDota's
    fault); [] means it succeeded and genuinely found nobody by that name.
    Callers need to tell these apart to show the right message."""
    try:
        results = _cached_get("/search", params={"q": name}, ttl=20) or []
    except OpenDotaError:
        return None
    return [
        {
            "account_id": r.get("account_id"),
            "nickname": r.get("personaname") or f"[{r.get('account_id')}]",
            "avatar_url": r.get("avatarfull"),
        }
        for r in results
        if r.get("account_id") is not None
    ][:5]


@dataclass
class PlayerStats:
    account_id: int
    nickname: str
    hidden: bool
    rank_tier: int = None
    total_games: int = 0
    winrate: float = None
    recent_matches: list = field(default_factory=list)  # [(hero_id, won: bool, match_id: int), ...], newest first, max 10
    top_heroes: list = field(default_factory=list)
    dotabuff_url: str = ""
    # Set only when hidden=True: WHY there's no data, so a caller can tell
    # "OpenDota is down/rate-limited, try again shortly" apart from a
    # genuinely private/unindexed profile (None means the latter - no error
    # occurred, OpenDota just has nothing to give).
    error_reason: str = None
    # True when this is a fallback: the live fetch failed but a previous
    # successful fetch for this account_id was reused instead of showing
    # nothing. stale_fetched_at is a time.time() timestamp for computing
    # "updated N minutes ago" in the UI.
    stale: bool = False
    stale_fetched_at: float = None


def fetch_player_stats(account_id):
    dotabuff_url = f"https://www.dotabuff.com/players/{account_id}"

    # The 4 endpoints below are independent of each other - fired together
    # instead of one-at-a-time so a single player's stats cost one round
    # trip's worth of latency, not four. Submitted via the module-level
    # pool (not awaited yet) so app.py's own per-player ThreadPoolExecutor
    # (used for a whole draft roster) doesn't end up gated behind this
    # function running everything serially inside each of its own threads.
    profile_f = _endpoint_executor.submit(_cached_get, f"/players/{account_id}", None, 30)
    wl_f = _endpoint_executor.submit(_cached_get, f"/players/{account_id}/wl", None, 30)
    recent_f = _endpoint_executor.submit(_cached_get, f"/players/{account_id}/recentMatches", None, 20)
    heroes_f = _endpoint_executor.submit(_cached_get, f"/players/{account_id}/heroes", None, 60)

    try:
        profile = profile_f.result()
    except OpenDotaError as e:
        with _stats_fallback_lock:
            fallback = _stats_fallback_cache.get(account_id)
        if fallback is not None:
            fetched_at, stale_stats = fallback
            return replace(stale_stats, stale=True, stale_fetched_at=fetched_at)
        return PlayerStats(account_id=account_id, nickname=f"[{account_id}]", hidden=True,
                            dotabuff_url=dotabuff_url, error_reason=e.reason)

    profile_info = profile.get("profile") or {}
    nickname = profile_info.get("personaname") or f"[{account_id}]"

    try:
        wl = wl_f.result()
    except OpenDotaError:
        wl = {}
    wins, losses = wl.get("win", 0), wl.get("lose", 0)
    total_games = wins + losses
    winrate = (wins / total_games * 100) if total_games else None
    hidden = total_games == 0 and not profile_info.get("personaname")

    try:
        recent = recent_f.result() or []
    except OpenDotaError:
        recent = []
    recent_matches = [
        (m.get("hero_id"), m.get("radiant_win") == (m.get("player_slot", 0) < 128), m.get("match_id"))
        for m in recent[:10]
    ]

    try:
        heroes = heroes_f.result() or []
    except OpenDotaError:
        heroes = []
    top_heroes = [h["hero_id"] for h in heroes if h.get("games", 0) > 0][:3]

    stats = PlayerStats(
        account_id=account_id, nickname=nickname, hidden=hidden,
        rank_tier=profile.get("rank_tier"), total_games=total_games, winrate=winrate,
        recent_matches=recent_matches, top_heroes=top_heroes, dotabuff_url=dotabuff_url,
    )
    if not hidden:
        # Only remember genuinely-fetched data as a fallback candidate - a
        # profile that's legitimately private/empty shouldn't get "revived"
        # later by this cache pretending it once had stats.
        with _stats_fallback_lock:
            _stats_fallback_cache[account_id] = (time.time(), stats)
    return stats
