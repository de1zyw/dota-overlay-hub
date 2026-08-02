"""Finds which Steam LIBRARY FOLDER actually contains Dota 2 - not just
Steam's own install root. Steam supports multiple library folders across
different drives/mounts (e.g. Steam itself on an HDD, games on a separate
SSD); the game files can be anywhere listed in Steam's own
steamapps/libraryfolders.vdf, not necessarily next to Steam's own install.
Never raises - falls back to the old hardcoded default
(~/.local/share/Steam) if detection fails for any reason, same behavior
as before this module existed."""
import os
import re

_DEFAULT = os.path.expanduser("~/.local/share/Steam")

_STEAM_ROOT_CANDIDATES = (
    "~/.local/share/Steam",
    "~/.steam/steam",
    "~/.steam/root",
)

# libraryfolders.vdf has one "path" key per library folder entry - the
# "apps" sub-block nested under each one only ever contains numeric
# app-id keys, never a literal "path" key, so a flat regex across the
# whole file (ignoring brace nesting entirely) is enough to pull out
# every library path without needing a real VDF parser.
_LIBRARY_PATH_RE = re.compile(r'"path"\s*"([^"]+)"')


def _find_steam_root():
    for candidate in _STEAM_ROOT_CANDIDATES:
        path = os.path.expanduser(candidate)
        if os.path.isdir(path):
            return path
    return None


def find_dota_library():
    """Returns the Steam library folder that actually has Dota 2 installed
    (i.e. `<this>/steamapps/common/dota 2 beta` exists), checking every
    library folder listed in libraryfolders.vdf - not just Steam's own
    install root. Falls back to Steam's own root, then to the old
    hardcoded default, if Dota isn't found anywhere. Never raises."""
    try:
        root = _find_steam_root()
        if not root:
            return _DEFAULT

        vdf_path = os.path.join(root, "steamapps", "libraryfolders.vdf")
        if not os.path.isfile(vdf_path):
            return root

        with open(vdf_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()

        for library_path in _LIBRARY_PATH_RE.findall(content):
            library_path = library_path.replace("\\\\", "/")
            if os.path.isdir(os.path.join(library_path, "steamapps", "common", "dota 2 beta")):
                return library_path

        return root
    except Exception:
        return _DEFAULT
