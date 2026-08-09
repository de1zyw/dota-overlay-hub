"""Curated per-category icon for the МОДЫ tab's sidebar/title, replacing
the raw d2pfx catalog's own "emoji" field (mod_catalog.py still returns
it verbatim - that module's job is a faithful mirror of the catalog data,
not UI opinions). The catalog's own choices are inconsistent (river/
wards/couriers all shared the same generic book emoji, several other
pairs collided too) and, where a matching Dota game asset actually
exists, a plain Unicode glyph is a worse stand-in than the real icon.

Two tiers:
- _REAL_ICON_LOADERS: categories with a clean, unambiguous real Dota
  asset. Most are a real downloaded PNG fetched via assets.py (network
  I/O on first call, cached to disk after - callers MUST run
  get_icon_path() off the Qt main thread). A few (_BUNDLED_ICONS) are
  hand-cropped once from the catalog's own mod files/preview screenshots
  and shipped as static files under assets/category_icons/ instead - no
  clean CDN icon existed for these, so the source was either a real
  installable mod asset (Cursors: an actual cursor bitmap, extracted
  from the catalog's own "Default Cursor" mod zip - the literal image
  these mods replace) or a cropped catalog preview screenshot (High
  Five, Hero Sounds - picked and cropped by hand, not reproducible by a
  formula, hence static rather than fetched).
- EMOJI: a hand-picked, collision-free fallback for every other category
  (and as a last-resort if a real icon's download ever fails)."""
import os

import assets

_BUNDLED_ICON_DIR = os.path.join(os.path.dirname(__file__), "assets", "category_icons")


def _bundled(filename):
    path = os.path.join(_BUNDLED_ICON_DIR, filename)
    return path if os.path.exists(path) else None


_REAL_ICON_LOADERS = {
    "ranks": lambda: assets.get_rank_icon_path(80),  # Immortal - no star variant, cleanest single icon
    "wards": lambda: assets.get_item_icon_path_by_name("ward_observer"),
    "couriers": lambda: assets.get_item_icon_path_by_name("courier"),
    "item-icons": lambda: assets.get_item_icon_path_by_name("blink"),
    "hero-items": lambda: assets.get_item_icon_path_by_name("mask_of_madness"),
    "roshan": lambda: assets.get_world_object_icon_path("roshan"),
    "ancient": lambda: assets.get_world_object_icon_path("ancient"),
    "tormentor": lambda: assets.get_world_object_icon_path("tormentor"),
    "towers": lambda: assets.get_world_object_icon_path("towers"),
    "creeps": lambda: assets.get_world_object_icon_path("creeps"),
    "ranged-attack": lambda: assets.get_world_object_icon_path("ranged-attack"),
    "heroes": lambda: assets.get_hero_icon_path_by_name("pudge"),
    "herofx": lambda: assets.get_ability_icon_path("pudge_meat_hook"),
    "cursors": lambda: _bundled("cursors.png"),
    "high-five": lambda: _bundled("high_five.png"),
    "hero-sounds": lambda: _bundled("hero_sounds.png"),
    "announcers": lambda: assets.get_world_object_icon_path("announcers"),
    "music": lambda: assets.get_world_object_icon_path("music"),
    # User-supplied Dota-themed icon collection (Telegram custom-emoji packs,
    # deduped by perceptual hash against the full ~2750-icon set before
    # picking) - each is a real Dota game-art icon, just not sourced from a
    # public CDN, hence bundled rather than fetched.
    "shaders": lambda: _bundled("shaders.png"),
    "optimization": lambda: _bundled("optimization.png"),
    "emblems": lambda: _bundled("emblems.png"),
    "pings": lambda: _bundled("pings.png"),
    "huds": lambda: _bundled("huds.png"),
    "creep-deny": lambda: _bundled("creep_deny.png"),
    "item-effects": lambda: _bundled("item_effects.png"),
    "ti-bp-effects": lambda: _bundled("ti_bp_effects.png"),
    "versus-screens": lambda: _bundled("versus_screens.png"),
    "trees": lambda: _bundled("trees.png"),
    "terrains": lambda: _bundled("terrains.png"),
    "pedestal": lambda: _bundled("pedestal.png"),
    "other": lambda: _bundled("other.png"),
    # Dota's own old voice-chat "yelling" indicator (the icon that popped up
    # near the minimap when a player talked loudly over push-to-talk, in
    # patches around 2013) - cropped from a real in-game screenshot the
    # user found (Steam Community, "Yelling mic icon", 2013-10-26).
    "sounds": lambda: _bundled("sounds.png"),
    "river": lambda: _bundled("river.png"),
    # A real Dota2_hero_emoji reaction gif (Techies, from the user's own
    # collection) rather than a static crop - "мега-килл" is inherently a
    # moment, not an object, so this is the one category icon that's
    # animated. is_animated() below is how callers know to load it as a
    # QMovie instead of a QPixmap.
    "mega-kill": lambda: _bundled("mega_kill.gif"),
    # No clean generic icon exists anywhere (Liquipedia has thousands of
    # specific loading-screen cosmetics but no "default" one the way Music
    # had "Default Music") - just a recognizable, distinct item icon so the
    # sidebar isn't stuck on an emoji, not meant to literally represent
    # "backgrounds".
    "backgrounds": lambda: assets.get_item_icon_path_by_name("aegis"),
}

_ANIMATED_CATEGORIES = {"mega-kill"}

# Every id from mod_catalog.get_categories(), each glyph used exactly
# once - the catalog's own data reused 📖 for wards/couriers/river and 🔊
# for four different audio categories, 👤 for heroes/hero-items, 🛠️ for
# cursors/optimization; none of that here.
EMOJI = {
    "shaders": "🎨",
    "ti-bp-effects": "🌟",
    "heroes": "👤",
    "terrains": "🏞️",
    "trees": "🌲",
    "creeps": "🐗",
    "creep-deny": "🎯",
    "emblems": "🏵",
    "backgrounds": "🖼️",
    "hero-items": "🎭",
    "herofx": "✨",
    "hero-sounds": "🗣️",
    "sounds": "🔊",
    "wards": "🔭",  # real icon normally wins - fallback only if the download fails
    "couriers": "🐴",
    "river": "🌊",
    "item-effects": "💥",
    "ranged-attack": "🏹",
    "pings": "📍",
    "huds": "🎴",
    "versus-screens": "🆚",
    "mega-kill": "💀",
    "announcers": "📢",
    "music": "🎵",
    "roshan": "🐲",
    "ancient": "🏛️",
    "tormentor": "🧊",
    "towers": "🗼",
    "pedestal": "🗿",
    "high-five": "🖐️",
    "item-icons": "👁️",
    "ranks": "🎖️",
    "cursors": "🖱️",
    "fonts": "🔤",
    "other": "⚙️",
    "optimization": "⚡",
}


def has_real_icon(category_id):
    return category_id in _REAL_ICON_LOADERS


def get_icon_path(category_id):
    """Real Dota image for this category, or None (no real icon exists
    for it, or the download failed). Does network I/O on a cache miss -
    call from a background thread, never the Qt main thread."""
    loader = _REAL_ICON_LOADERS.get(category_id)
    return loader() if loader else None


def is_animated(category_id):
    """True for the handful of icons that are a gif, not a still image -
    callers should load these with QMovie, not QPixmap (a bare QPixmap
    silently renders only the first frame of a gif, no error)."""
    return category_id in _ANIMATED_CATEGORIES


def get_emoji(category_id, fallback=""):
    return EMOJI.get(category_id, fallback)
