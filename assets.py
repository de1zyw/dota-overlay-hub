"""Fetches and locally caches hero/rank icon images from public, no-auth-needed
CDN URLs (Steam's static CDN for heroes, OpenDota's own asset host for ranks).
Never raises - a failed download just means no icon for that row, not a crash."""
import os

import requests

from opendota_client import _cached_get

CACHE_DIR = os.path.join(os.path.dirname(__file__), ".assets_cache")
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

os.makedirs(CACHE_DIR, exist_ok=True)

_hero_internal_names = None


def _get_hero_internal_name(hero_id):
    global _hero_internal_names
    if _hero_internal_names is None:
        heroes = _cached_get("/heroes", ttl=3600 * 24) or []
        _hero_internal_names = {
            h["id"]: h["name"].removeprefix("npc_dota_hero_") for h in heroes
        }
    return _hero_internal_names.get(hero_id)


def _download(url, dest_path):
    if os.path.exists(dest_path):
        return dest_path
    try:
        resp = requests.get(url, timeout=10)
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
