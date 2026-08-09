"""Named, saved mod selections ("наборы") - lets the user build a cart of
mods once (checkboxes across any category, see mods_page.py's _ModsPage)
and reinstall that exact same set again later with one click, instead of
re-picking every mod by hand each time.

Stores only (category_id, mod_name) pairs, never the full mod dict - the
catalog itself (mod_catalog.py) is always re-queried when a preset is
loaded, so a preset never goes stale even if the catalog's own data for
that mod changes (new preview, moved category, etc)."""
import json
import os

PRESETS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mod_presets.json")


def load_all():
    """{preset_name: [[category_id, mod_name], ...]}"""
    try:
        with open(PRESETS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except (OSError, json.JSONDecodeError):
        pass
    return {}


def save(name, items):
    """items: iterable of (category_id, mod_name) pairs."""
    name = (name or "").strip()
    if not name:
        return False
    presets = load_all()
    presets[name] = [[category_id, mod_name] for category_id, mod_name in items]
    try:
        with open(PRESETS_PATH, "w", encoding="utf-8") as f:
            json.dump(presets, f, indent=2, ensure_ascii=False)
        return True
    except OSError:
        return False


def delete(name):
    presets = load_all()
    if name not in presets:
        return
    presets.pop(name)
    try:
        with open(PRESETS_PATH, "w", encoding="utf-8") as f:
            json.dump(presets, f, indent=2, ensure_ascii=False)
    except OSError:
        pass
