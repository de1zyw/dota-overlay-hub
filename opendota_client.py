"""Thin OpenDota client - throttled, cached, retrying.
Adapted from ~/dota_stats_bot/opendota_api.py, trimmed to what the overlay needs."""
import collections
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace

import requests

import error_codes

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
_STATS_FALLBACK_MAX = 200
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
    of one generic "unavailable" for every case.

    code is the real HTTP status (e.g. 429, 503) when OpenDota actually
    responded, or one of error_codes.py's own hex codes when it never got
    that far (DNS/connection/timeout/malformed body)."""

    def __init__(self, message, reason="http_error", code=None):
        super().__init__(message)
        self.reason = reason
        self.code = code


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
    last_code = error_codes.CONNECTION_ERROR
    for attempt in range(MAX_RETRIES):
        _throttle()
        try:
            resp = _session.get(f"{BASE_URL}{endpoint}", params=params, timeout=timeout)
        except requests.exceptions.Timeout as e:
            last_error, last_reason, last_code = str(e), "network", error_codes.TIMEOUT
            time.sleep((2 ** attempt) + random.uniform(0, 0.5))
            continue
        except requests.exceptions.RequestException as e:
            last_error, last_reason, last_code = str(e), "network", error_codes.CONNECTION_ERROR
            time.sleep((2 ** attempt) + random.uniform(0, 0.5))
            continue
        if resp.status_code in RETRYABLE_STATUSES:
            last_error = f"HTTP {resp.status_code}"
            last_reason = "rate_limited" if resp.status_code == 429 else "server_error"
            last_code = resp.status_code
            if attempt < MAX_RETRIES - 1:
                time.sleep((2 ** attempt) + random.uniform(0, 0.5))
                continue
        try:
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.RequestException as e:
            raise OpenDotaError(f"OpenDota request failed: {e}", reason=last_reason, code=resp.status_code)
        except ValueError as e:
            # resp.json() on a 200 with a malformed/non-JSON body (CDN
            # error page, truncated response under rate-limit, etc.) - a
            # JSONDecodeError here used to escape this function entirely,
            # bypassing every caller's OpenDotaError->empty-result fallback.
            raise OpenDotaError(f"OpenDota returned invalid JSON: {e}", reason="invalid_json", code=error_codes.INVALID_JSON)
    raise OpenDotaError(
        f"OpenDota unreachable after {MAX_RETRIES} attempts ({last_error})", reason=last_reason, code=last_code
    )


def _cached_get(endpoint, params=None, ttl=30):
    key = (endpoint, tuple(sorted((params or {}).items())))
    with _cache_lock:
        entry = _cache.get(key)
        if entry and entry[0] > time.time():
            return entry[1]
    data = _get(endpoint, params)
    with _cache_lock:
        _cache[key] = (time.time() + ttl, data)
        # A key looked up once (e.g. a one-off account_id) and never again
        # would otherwise sit here forever - nothing ever purged expired
        # entries. Sweep on write instead of a separate timer thread, since
        # writes already happen roughly as often as new keys are added.
        now = time.time()
        expired = [k for k, (exp, _) in _cache.items() if exp <= now]
        for k in expired:
            del _cache[k]
    return data


def fetch_match_roster(match_id):
    """Returns [(team, team_slot, account_id, hero_id, items), ...] for a
    match - hero_id and items go beyond the shape
    lobby_watcher.parse_latest_match() used to return, since that source
    never had hero picks or a final build bundled in (GSI supplied hero
    picks separately, and never had item data at all); OpenDota's match
    data has all of it at once. account_id is None for a player whose
    profile is private (OpenDota itself doesn't get an account_id for them
    even inside match data - that player still shows up with a hero_id,
    just without stats being fetchable for them). items is the final
    6-slot inventory + neutral item, as raw item_ids (0 = empty slot,
    kept rather than filtered out so callers can still show 7 slot
    positions if they want to).

    Returns None if OpenDota doesn't have this match yet (still in
    progress, or not indexed yet - confirmed live that this can take a
    while after a real match, see last_match_watcher.py) or on any
    OpenDota-side error. Callers decide whether/how long to keep retrying."""
    try:
        data = _cached_get(f"/matches/{match_id}", ttl=15)
    except OpenDotaError:
        return None
    players = data.get("players") or []
    if len(players) != 10 or not all(p.get("hero_id") for p in players):
        return None
    roster = []
    for p in players:
        slot = p.get("player_slot") or 0
        hero_id = p.get("hero_id")
        items = [
            p.get("item_0", 0), p.get("item_1", 0), p.get("item_2", 0),
            p.get("item_3", 0), p.get("item_4", 0), p.get("item_5", 0),
            p.get("item_neutral", 0),
        ]
        if slot < 128:
            roster.append(("radiant", slot, p.get("account_id"), hero_id, items))
        else:
            roster.append(("dire", slot - 128, p.get("account_id"), hero_id, items))
    return roster


# Cheap/starting-gold items filtered out of key_purchases below - they're
# bought within the first ~90s by every player regardless of build and
# would drown out the actually build-defining purchases. Not exhaustive by
# design (consumables like tango/clarity/wards are cheap enough on their
# own that a stray one slipping through doesn't hurt readability).
_TRIVIAL_ITEM_KEYS = {
    "tango", "tango_single", "flask", "clarity", "faerie_fire", "enchanted_mango",
    "branches", "circlet", "mantle", "gauntlets", "slippers", "sobi_mask",
    "quarterstaff", "ring_of_protection", "iron_branch", "ward_observer",
    "ward_sentry", "smoke_of_deceit", "tpscroll", "gem", "boots",
}


def fetch_match_recap(match_id, account_id):
    """Returns a PlayerStats populated with account_id's own performance in
    match_id (kills/deaths/gpm/benchmarks/etc.), or None under the exact
    same conditions fetch_match_roster returns None (not-yet-indexed match,
    OpenDota error, account_id not present as a player in this match).
    Shares fetch_match_roster's cache entry - calling both for the same
    match_id costs one real HTTP request, not two, within the 15s TTL."""
    try:
        data = _cached_get(f"/matches/{match_id}", ttl=15)
    except OpenDotaError:
        return None
    players = data.get("players") or []
    me = next((p for p in players if p.get("account_id") == account_id), None)
    if me is None:
        return None

    purchases = [
        (entry["key"], entry["time"])
        for entry in (me.get("purchase_log") or [])
        if entry.get("key") and entry["key"] not in _TRIVIAL_ITEM_KEYS and entry.get("time", -1) >= 0
    ]

    return PlayerStats(
        account_id=account_id,
        nickname=me.get("personaname") or "?",
        hidden=False,
        match_id=match_id,
        hero_id=me.get("hero_id"),
        won=bool(me.get("win")),
        duration=data.get("duration"),
        kills=me.get("kills", 0), deaths=me.get("deaths", 0), assists=me.get("assists", 0),
        gpm=me.get("gold_per_min", 0), xpm=me.get("xp_per_min", 0),
        last_hits=me.get("last_hits", 0), denies=me.get("denies", 0),
        hero_damage=me.get("hero_damage", 0), tower_damage=me.get("tower_damage", 0),
        hero_healing=me.get("hero_healing", 0),
        benchmarks={k: v.get("pct") for k, v in (me.get("benchmarks") or {}).items() if v.get("pct") is not None},
        key_purchases=purchases,
        dotabuff_url=f"https://www.dotabuff.com/matches/{match_id}",
    )


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


def fetch_peers(account_id, limit=3):
    """Top `limit` most-frequent teammates by games played together, or
    None on any OpenDota-side error (same convention as search_players -
    None means "couldn't ask", not "nobody found"). Self-account use only
    (see player_stats_window.py) - this endpoint is about the QUERIED
    account's own peers, not meaningful on a looked-up stranger's profile."""
    try:
        peers = _cached_get(f"/players/{account_id}/peers", ttl=300) or []
    except OpenDotaError:
        return None
    peers = sorted(peers, key=lambda p: p.get("games", 0), reverse=True)[:limit]
    return [
        {
            "account_id": p.get("account_id"),
            "personaname": p.get("personaname") or f"[{p.get('account_id')}]",
            "avatarfull": p.get("avatarfull"),
            "win": p.get("win", 0),
            "games": p.get("games", 0),
        }
        for p in peers
    ]


@dataclass
class RecentMatch:
    hero_id: int
    won: bool
    match_id: int
    kills: int
    deaths: int
    assists: int
    gpm: int
    xpm: int


@dataclass
class PlayerStats:
    account_id: int
    nickname: str
    hidden: bool
    rank_tier: int = None
    # Non-null only for top-tier leaderboard players - confirmed live that
    # exact MMR (mmr_estimate/competitive_rank/solo_competitive_rank) is
    # None for a normal account, Valve stopped exposing it publicly in
    # 2019. This is the only additional real rank signal OpenDota has.
    leaderboard_rank: int = None
    total_games: int = 0
    winrate: float = None
    recent_matches: list = field(default_factory=list)  # list[RecentMatch], newest first, max 10
    top_heroes: list = field(default_factory=list)
    # Only populated by app.py's last-match-recap path (fetch_match_roster
    # is the only source with per-match item data) - empty for self-stats/
    # profile-lookup, which aren't about one specific match. 7 raw item_ids
    # (6 inventory slots + neutral item), 0 = empty slot.
    items: list = field(default_factory=list)
    # Below: only populated by fetch_match_recap() (the "last match" hotkey's
    # own-performance recap), None for every other caller of this dataclass.
    match_id: int = None
    hero_id: int = None
    won: bool = None
    duration: int = None
    kills: int = None
    deaths: int = None
    assists: int = None
    gpm: int = None
    xpm: int = None
    last_hits: int = None
    denies: int = None
    hero_damage: int = None
    tower_damage: int = None
    hero_healing: int = None
    # {stat_name: percentile 0.0-1.0 vs same hero/bracket} - straight from
    # OpenDota's own "benchmarks" field (confirmed live against a real
    # completed match, 2026-08-19: no separate request/param needed, it's
    # already in the same /matches/{id} payload fetch_match_roster reads).
    benchmarks: dict = field(default_factory=dict)
    # [(item_key, purchase_second), ...] in purchase order, consumables and
    # starting-gold items filtered out by the caller - see fetch_match_recap.
    key_purchases: list = field(default_factory=list)
    dotabuff_url: str = ""
    # Set only when hidden=True: WHY there's no data, so a caller can tell
    # "OpenDota is down/rate-limited, try again shortly" apart from a
    # genuinely private/unindexed profile (None means the latter - no error
    # occurred, OpenDota just has nothing to give).
    error_reason: str = None
    # The real HTTP status (e.g. 429) when OpenDota responded, or one of
    # error_codes.py's own hex codes when it never got that far - shown
    # alongside error_reason's human message for exact bug-report-ability.
    error_code: int = None
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
                            dotabuff_url=dotabuff_url, error_reason=e.reason, error_code=e.code)

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
        RecentMatch(
            hero_id=m.get("hero_id"),
            won=m.get("radiant_win") == (m.get("player_slot", 0) < 128),
            match_id=m.get("match_id"),
            kills=m.get("kills") or 0,
            deaths=m.get("deaths") or 0,
            assists=m.get("assists") or 0,
            gpm=m.get("gold_per_min") or 0,
            xpm=m.get("xp_per_min") or 0,
        )
        for m in recent[:10]
    ]

    try:
        heroes = heroes_f.result() or []
    except OpenDotaError:
        heroes = []
    top_heroes = [
        (h["hero_id"], h.get("games", 0), h.get("win", 0))
        for h in heroes if h.get("games", 0) > 0
    ][:3]

    stats = PlayerStats(
        account_id=account_id, nickname=nickname, hidden=hidden,
        rank_tier=profile.get("rank_tier"), leaderboard_rank=profile.get("leaderboard_rank"),
        total_games=total_games, winrate=winrate,
        recent_matches=recent_matches, top_heroes=top_heroes, dotabuff_url=dotabuff_url,
    )
    if not hidden:
        # Only remember genuinely-fetched data as a fallback candidate - a
        # profile that's legitimately private/empty shouldn't get "revived"
        # later by this cache pretending it once had stats.
        with _stats_fallback_lock:
            _stats_fallback_cache[account_id] = (time.time(), stats)
            # Unlike _cache above this is meant to live indefinitely (it's
            # the outage fallback), so a TTL sweep doesn't apply - cap the
            # count instead and drop the oldest once a long session has
            # looked up more distinct players than any one draft/lobby
            # would realistically ever contain.
            if len(_stats_fallback_cache) > _STATS_FALLBACK_MAX:
                oldest_id = min(_stats_fallback_cache, key=lambda k: _stats_fallback_cache[k][0])
                del _stats_fallback_cache[oldest_id]
    return stats
