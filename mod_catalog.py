"""Fetches and locally caches the Dota2PornFx open mod catalog (GPL-3.0,
github.com/h6rd/Dota2PornFxWeb) - a community-maintained repository of
cosmetic Dota 2 mods (skins/terrains/announcers/music/shaders/etc), served
as static JSON straight from the repo's raw GitHub content. We don't embed
any of their JS/website code (different stack - Electron/web vs our PyQt) -
this is an independent reimplementation of the same "browse + one-click
install" idea, talking to their same public data files. Never raises on
network failure - a stale/missing cache just means an empty catalog page,
not a crash."""
import json
import os
import time

import requests

CACHE_DIR = os.path.join(os.path.dirname(__file__), ".mod_catalog_cache")
os.makedirs(CACHE_DIR, exist_ok=True)

REPO_BASE = "https://raw.githubusercontent.com/h6rd/Dota2PornFxWeb/main"
CATALOG_TTL_SECONDS = 3600 * 6

# "guides"/"tools"/"packs" are the catalog's own hidden categories (not
# real mods); "sites"/"news" are external links (their "file"/"url" fields
# point at other websites, not a downloadable .vpk/.zip) - none of these
# five are installable, so they never show up as a browsable category here.
EXCLUDED_CATEGORIES = {"guides", "tools", "packs", "sites", "news"}

_session = requests.Session()

_mods_data = None
_categories = None


def _cached_json(url, cache_name, ttl):
    cache_path = os.path.join(CACHE_DIR, cache_name)
    if os.path.exists(cache_path) and time.time() - os.path.getmtime(cache_path) < ttl:
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            pass
    try:
        resp = _session.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except (requests.exceptions.RequestException, ValueError):
        # Network's down / GitHub unreachable - fall back to whatever's on
        # disk, even if past its TTL, rather than showing an empty catalog.
        if os.path.exists(cache_path):
            try:
                with open(cache_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (OSError, json.JSONDecodeError):
                pass
        return None
    tmp_path = f"{cache_path}.tmp{os.getpid()}"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tmp_path, cache_path)
    except OSError:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
    return data


def get_categories():
    """Ordered list of {id, emoji, name} for every browsable mod category."""
    global _categories
    if _categories is not None:
        return _categories
    constants = _cached_json(
        f"{REPO_BASE}/assets/data/constants.json", "constants.json", CATALOG_TTL_SECONDS
    ) or {}
    translations = constants.get("translations", {})
    raw_categories = constants.get("categories", [])
    _categories = [
        {"id": c["id"], "emoji": c.get("emoji", ""), "name": translations.get(c["id"], c["id"])}
        for c in raw_categories
        if c["id"] not in EXCLUDED_CATEGORIES
    ]
    return _categories


def _flatten_mods(raw):
    """A category's raw value is either a flat list of mods, or a
    {"groups": [{"id", "name", "mods": [...]}]} structure (grouped by hero -
    hero-items/creep-deny/creeps/towers/item-effects). Flattens both into
    one list of mods."""
    if isinstance(raw, dict) and "groups" in raw:
        out = []
        for group in raw["groups"]:
            out.extend(group.get("mods", []))
        return out
    if isinstance(raw, list):
        return [m for m in raw if isinstance(m, dict)]
    return []


def _expand_styles(mods):
    """A mod with a "styles" list (color/skin variants) has no file/preview
    of its own - each style is really its own installable item, sharing the
    parent's display name plus its own style label."""
    out = []
    for mod in mods:
        styles = mod.get("styles")
        if not styles:
            out.append(mod)
            continue
        for style in styles:
            label = style.get("label")
            out.append({
                **mod,
                "name": f"{mod['name']} ({label})" if label else mod["name"],
                "file": style.get("file"),
                "preview": style.get("preview"),
                "styles": None,
            })
    return out


def get_mods(category_id):
    """All installable mods in one category, groups/styles already
    flattened into a single flat list."""
    global _mods_data
    if _mods_data is None:
        raw = _cached_json(
            f"{REPO_BASE}/assets/data/mods.json", "mods.json", CATALOG_TTL_SECONDS
        ) or {}
        _mods_data = raw.get("modsData", {})
    return _expand_styles(_flatten_mods(_mods_data.get(category_id)))


def get_download_url(category_id, filename):
    if not filename or filename.startswith("http"):
        return None
    return f"{REPO_BASE}/assets/files/{category_id}/{filename}"


def get_preview_path(category_id, preview_filename):
    """Downloads (once, cached forever - previews don't change filename
    without becoming a different mod entry) and returns a local path for a
    mod's preview thumbnail. Safe to call from a background thread only -
    does a blocking network request on a cache miss."""
    if not preview_filename:
        return None
    dest = os.path.join(CACHE_DIR, "previews", category_id, preview_filename)
    if os.path.exists(dest):
        return dest
    url = f"{REPO_BASE}/assets/previews/{category_id}/{preview_filename}"
    try:
        resp = _session.get(url, timeout=10)
        resp.raise_for_status()
    except requests.exceptions.RequestException:
        return None
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    tmp_path = f"{dest}.tmp{os.getpid()}"
    try:
        with open(tmp_path, "wb") as f:
            f.write(resp.content)
        os.replace(tmp_path, dest)
    except OSError:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        return None
    return dest
