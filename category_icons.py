"""Curated per-category icon for the МОДЫ tab's sidebar/title, replacing
the raw d2pfx catalog's own "emoji" field (mod_catalog.py still returns
it verbatim - that module's job is a faithful mirror of the catalog data,
not UI opinions). The catalog's own choices are inconsistent (river/
wards/couriers all shared the same generic book emoji, several other
pairs collided too) and, where a matching Dota game asset actually
exists, a plain Unicode glyph is a worse stand-in than the real icon.

Two tiers:
- _REAL_ICON_LOADERS: categories with a clean, unambiguous real Dota
  asset (a specific in-game item/object, not a broad concept like
  "Shaders" or "Optimization") - backed by a real downloaded PNG via
  assets.py. Each loader does network I/O on first call (cached to disk
  after) - callers MUST run get_icon_path() off the Qt main thread.
- EMOJI: a hand-picked, collision-free fallback for every other category
  (and as a last-resort if a real icon's download ever fails)."""
import assets

_REAL_ICON_LOADERS = {
    "ranks": lambda: assets.get_rank_icon_path(80),  # Immortal - no star variant, cleanest single icon
    "wards": lambda: assets.get_item_icon_path_by_name("ward_observer"),
    "couriers": lambda: assets.get_item_icon_path_by_name("courier"),
    "item-icons": lambda: assets.get_item_icon_path_by_name("blink"),
    "roshan": lambda: assets.get_world_object_icon_path("roshan"),
    "ancient": lambda: assets.get_world_object_icon_path("ancient"),
    "tormentor": lambda: assets.get_world_object_icon_path("tormentor"),
    "towers": lambda: assets.get_world_object_icon_path("towers"),
}

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


def get_emoji(category_id, fallback=""):
    return EMOJI.get(category_id, fallback)
