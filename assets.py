"""Fetches and locally caches hero/rank icon images from public, no-auth-needed
CDN URLs (Steam's static CDN for heroes, OpenDota's own asset host for ranks).
Never raises - a failed download just means no icon for that row, not a crash."""
import os
from concurrent.futures import ThreadPoolExecutor

import requests

import platform_utils
from opendota_client import _cached_get

CACHE_DIR = os.path.join(platform_utils.data_dir(), ".assets_cache")
# Reused across every icon download (a whole draft roster's worth of hero
# icons at once, first time any of them is seen) - keep-alive skips a
# fresh TCP+TLS handshake per icon.
_session = requests.Session()
HERO_ICON_BASE = "https://cdn.cloudflare.steamstatic.com/apps/dota2/images/dota_react/heroes/icons"
RANK_ICON_BASE = "https://www.opendota.com/assets/images/dota2/rank_icons"
# Liquipedia's own asset host (not Steam/OpenDota) - hosts the actual in-game
# faction emblems (Radiant's ancient, Dire's fiery towers) as real PNGs.
# Found by querying Liquipedia's public MediaWiki API for the images used on
# its "Factions" page, then verifying with `file` that the bytes are a real
# PNG (not an HTML shell) - Steam's dota_react CDN and OpenDota's asset host
# have no faction icons at any path tried for this.
FACTION_ICON_URLS = {
    "radiant": "https://liquipedia.net/commons/images/b/b6/Dota2_Radiant_icon.png",
    "dire": "https://liquipedia.net/commons/images/2/2c/Dota2_Dire_icon.png",
}

# Same Liquipedia asset host, same "verify with `file` that it's a real PNG"
# process as FACTION_ICON_URLS above - used for mods_page.py's category
# sidebar icons (category_icons.py) where the category is a specific named
# in-game object (Roshan, the Ancient, ...) with no matching entry on
# Steam's own item/hero icon CDNs. Found by querying each object's own
# Liquipedia page for embedded "<Name> (mapicon|icon) dota2 gameasset.png"
# files (Liquipedia articles list every image used on the page via the
# ordinary MediaWiki `prop=images` API) and picking the plain/generic one,
# not a specific cosmetic reskin.
WORLD_OBJECT_ICON_URLS = {
    "roshan": "https://liquipedia.net/commons/images/7/75/Roshan_icon_dota2_gameasset.png",
    "ancient": "https://liquipedia.net/commons/images/6/6f/Ancient_%28Radiant%29_icon_dota2_wikiasset.png",
    "tormentor": "https://liquipedia.net/commons/images/a/a3/Tormentor_%28Radiant%29_icon_dota2_gameasset.png",
    "towers": "https://liquipedia.net/commons/images/c/c9/Tower_%28Radiant%29_icon_dota2_gameasset.png",
    "creeps": "https://liquipedia.net/commons/images/4/40/Melee_Creep_%28Radiant%29_icon_dota2_gameasset.png",
    "ranged-attack": "https://liquipedia.net/commons/images/1/17/Ranged_Creep_%28Radiant%29_icon_dota2_wikiasset.png",
    # Valve's own cosmetic-slot badge icons (shown in the in-game shop next
    # to any item of that type) - the exact same graphic the d2pfx catalog
    # blurs and puts a big text label over for its own category banners;
    # this is that same icon at full resolution, no blur/text.
    "announcers": "https://liquipedia.net/commons/images/b/b4/Cosmetic_icon_Announcer_Kunkka_%26_Tidehunter.png",
    "music": "https://liquipedia.net/commons/images/9/9e/Cosmetic_icon_Default_Music.png",
}

os.makedirs(CACHE_DIR, exist_ok=True)

_hero_internal_names = None
_item_internal_names = None
ITEM_ICON_BASE = "https://cdn.cloudflare.steamstatic.com/apps/dota2/images/dota_react/items"
ABILITY_ICON_BASE = "https://cdn.cloudflare.steamstatic.com/apps/dota2/images/dota_react/abilities"


def _get_hero_internal_name(hero_id):
    global _hero_internal_names
    if _hero_internal_names is None:
        heroes = _cached_get("/heroes", ttl=3600 * 24) or []
        _hero_internal_names = {
            h["id"]: h["name"].removeprefix("npc_dota_hero_") for h in heroes
        }
    return _hero_internal_names.get(hero_id)


def _get_item_internal_name(item_id):
    # /constants/item_ids maps numeric item_id (the same numbers matches
    # store in item_0..item_5) to the internal name the icon CDN expects -
    # confirmed live against a real match's item_0 (1097 -> "disperser",
    # a real fetchable icon). item_id 0 means an empty slot, not a real item.
    global _item_internal_names
    if _item_internal_names is None:
        raw = _cached_get("/constants/item_ids", ttl=3600 * 24) or {}
        _item_internal_names = {int(k): v for k, v in raw.items()}
    return _item_internal_names.get(item_id)


def _download(url, dest_path):
    if os.path.exists(dest_path):
        return dest_path
    try:
        resp = _session.get(url, timeout=10)
        resp.raise_for_status()
    except requests.exceptions.RequestException:
        return None
    # Written to a temp path and renamed into place atomically - a
    # connection drop or full disk mid-write used to leave a partial file
    # at dest_path, which the exists() check above would then treat as
    # permanently cached and never retry.
    tmp_path = f"{dest_path}.tmp{os.getpid()}"
    try:
        with open(tmp_path, "wb") as f:
            f.write(resp.content)
        os.replace(tmp_path, dest_path)
    except OSError:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        return None
    return dest_path


def get_hero_icon_path(hero_id):
    if not hero_id:
        return None
    name = _get_hero_internal_name(hero_id)
    if not name:
        return None
    dest = os.path.join(CACHE_DIR, f"hero_icon_{hero_id}.png")
    return _download(f"{HERO_ICON_BASE}/{name}.png", dest)


def get_item_icon_path(item_id):
    if not item_id:  # 0 (or None) means an empty inventory slot
        return None
    name = _get_item_internal_name(item_id)
    if not name:
        return None
    dest = os.path.join(CACHE_DIR, f"item_icon_{item_id}.png")
    return _download(f"{ITEM_ICON_BASE}/{name}.png", dest)


def get_item_icon_path_by_name(internal_name):
    """Same CDN as get_item_icon_path, but for callers that already know
    the item's internal name (e.g. a fixed, hand-picked representative
    icon for a UI element) and have no item_id to resolve it from."""
    if not internal_name:
        return None
    dest = os.path.join(CACHE_DIR, f"item_icon_name_{internal_name}.png")
    return _download(f"{ITEM_ICON_BASE}/{internal_name}.png", dest)


def get_hero_icon_path_by_name(internal_name):
    """Same CDN as get_hero_icon_path, but for a fixed, hand-picked
    representative hero (e.g. category_icons.py's "Heroes" icon) rather
    than resolving one from a real hero_id via OpenDota."""
    if not internal_name:
        return None
    dest = os.path.join(CACHE_DIR, f"hero_icon_name_{internal_name}.png")
    return _download(f"{HERO_ICON_BASE}/{internal_name}.png", dest)


def get_ability_icon_path(internal_name):
    if not internal_name:
        return None
    dest = os.path.join(CACHE_DIR, f"ability_icon_{internal_name}.png")
    return _download(f"{ABILITY_ICON_BASE}/{internal_name}.png", dest)


def get_rank_icon_path(rank_tier):
    if not rank_tier:
        return None
    tier = rank_tier // 10
    stars = rank_tier % 10
    if tier == 8:
        filename = "rank_icon_8"
    else:
        filename = f"rank_icon_{tier}_{stars}" if stars else f"rank_icon_{tier}"
    dest = os.path.join(CACHE_DIR, f"{filename}.png")
    return _download(f"{RANK_ICON_BASE}/{filename}.png", dest)


def get_faction_icon_path(team):
    url = FACTION_ICON_URLS.get(team)
    if not url:
        return None
    dest = os.path.join(CACHE_DIR, f"faction_icon_{team}.png")
    return _download(url, dest)


def get_world_object_icon_path(key):
    url = WORLD_OBJECT_ICON_URLS.get(key)
    if not url:
        return None
    dest = os.path.join(CACHE_DIR, f"world_icon_{key}.png")
    return _download(url, dest)


def get_avatar_path(account_id, avatar_url):
    """Unlike hero/rank icons (a small fixed enumerable set, prefetched by
    prefetch_all_icons), peer avatars are one arbitrary URL per arbitrary
    account_id - unbounded, so this is fetched on demand, not prefetched."""
    if not avatar_url or not account_id:
        return None
    dest = os.path.join(CACHE_DIR, f"avatar_{account_id}.jpg")
    return _download(avatar_url, dest)


def prefetch_all_icons():
    """Warms the on-disk cache for every icon this app can ever need, so a
    real draft never has to hit get_hero_icon_path()/get_rank_icon_path()
    cold. Those are called directly from render_lobby() on the Qt MAIN
    thread - a cache miss there means _download()'s synchronous network
    request (up to a 10s timeout) freezes the whole UI, and a fresh
    install starts with an EMPTY cache, so the very first draft would hit
    this for every single hero/rank shown. Meant to be kicked off once,
    from a background thread, at app startup - well before matchmaking
    could possibly find a game, so it's always long done by the first
    real draft. Steam's static CDN (heroes) isn't the throttled OpenDota
    API, so this doesn't compete with real gameplay requests for that
    budget."""
    try:
        heroes = _cached_get("/heroes", ttl=3600 * 24) or []
    except Exception:
        heroes = []
    hero_ids = [h["id"] for h in heroes if h.get("id")]

    # tiers 1-7 x stars 1-5, plus tier 8 (Immortal - one icon, no stars
    # variant) - every rank_icon_path this app could ever be asked for.
    rank_tiers = [t * 10 + s for t in range(1, 8) for s in range(1, 6)] + [80]

    jobs = (
        [(get_hero_icon_path, hero_id) for hero_id in hero_ids]
        + [(get_rank_icon_path, tier) for tier in rank_tiers]
        + [(get_faction_icon_path, team) for team in FACTION_ICON_URLS]
    )
    with ThreadPoolExecutor(max_workers=16, thread_name_prefix="asset-prefetch") as pool:
        list(pool.map(lambda job: job[0](job[1]), jobs))
