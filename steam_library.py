"""Finds which Steam LIBRARY FOLDER actually contains Dota 2 - not just
Steam's own install root. Steam supports multiple library folders across
different drives/mounts (e.g. Steam itself on an HDD, games on a separate
SSD); the game files can be anywhere listed in Steam's own
steamapps/libraryfolders.vdf, not necessarily next to Steam's own install.
Never raises - falls back to a hardcoded per-OS default if detection
fails for any reason, same behavior as before this module existed.

Cross-platform: Linux detection (dotfiles under $HOME, flatpak/snap
paths, /run/media mount scan) and Windows detection (registry keys the
real Steam client itself writes, Program Files paths, drive-letter scan)
are both real, not guessed - the Windows registry keys match what the
catalog's own Install.bat scripts (mod_tools.py's Background Changer/
cursor/font mods) already query the same way."""
import os
import re
import sys

import platform_utils

IS_WINDOWS = sys.platform == "win32"

if IS_WINDOWS:
    import winreg

_DEFAULT = (
    r"C:\Program Files (x86)\Steam" if IS_WINDOWS else os.path.expanduser("~/.local/share/Steam")
)

# Manual escape hatch: if auto-detection (registered Steam libraries, then
# scanning /run/media, /media, /mnt - or drive letters on Windows) fails
# for any reason - e.g. the drive was mounted by root and isn't readable
# by the current user - drop the exact library folder path (the one
# containing "steamapps") into this file, one line, no quotes. Checked
# first, before any auto-detection.
_OVERRIDE_FILE = os.path.join(platform_utils.data_dir(), "steam_library_override.txt")


def load_library_override():
    """Raw override text as currently saved, "" if none - for pre-filling
    the Settings-page field with whatever's already set, distinct from
    find_dota_library()'s own read of this same file (that one only
    returns it if _has_dota() confirms it's actually valid)."""
    try:
        with open(_OVERRIDE_FILE, "r", encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def save_library_override(path):
    """Settings-page write path for the manual escape hatch documented
    above - same file, same one-line-no-quotes format a user would've
    edited by hand. Empty path deletes the override file instead of
    writing an empty one, so auto-detection resumes. Returns True/False,
    never raises - the caller (a UI click handler) reports failure itself."""
    path = (path or "").strip()
    try:
        if not path:
            if os.path.isfile(_OVERRIDE_FILE):
                os.remove(_OVERRIDE_FILE)
            return True
        with open(_OVERRIDE_FILE, "w", encoding="utf-8") as f:
            f.write(path)
        return True
    except OSError:
        return False


_STEAM_ROOT_CANDIDATES = (
    "~/.local/share/Steam",
    "~/.steam/steam",
    "~/.steam/root",
    "~/.var/app/com.valve.Steam/.local/share/Steam",  # flatpak
    "~/snap/steam/common/.local/share/Steam",  # snap
)

_WINDOWS_STEAM_REGISTRY_KEYS = (
    # (hive, subkey, value_name) - HKCU\...\SteamPath is what the running
    # Steam client itself writes on every launch (most reliable, always
    # points at wherever it's actually installed); the HKLM InstallPath
    # keys are what the installer writes and what third-party installers
    # (the catalog's own Install.bat scripts) query, kept as a fallback
    # for a machine where Steam was installed but never actually run yet.
    (None, r"Software\Valve\Steam", "SteamPath"),
    (None, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
    (None, r"SOFTWARE\Valve\Steam", "InstallPath"),
)
_WINDOWS_STEAM_FALLBACK_PATHS = (
    r"C:\Program Files (x86)\Steam",
    r"C:\Program Files\Steam",
)

# libraryfolders.vdf has one "path" key per library folder entry - the
# "apps" sub-block nested under each one only ever contains numeric
# app-id keys, never a literal "path" key, so a flat regex across the
# whole file (ignoring brace nesting entirely) is enough to pull out
# every library path without needing a real VDF parser.
_LIBRARY_PATH_RE = re.compile(r'"path"\s*"([^"]+)"')

# Fallback for drives Steam itself doesn't know about yet (e.g. a mounted
# partition that isn't registered as a Steam library folder) - scanned
# only if the libraryfolders.vdf approach above finds nothing.
_EXTRA_MOUNT_ROOTS = ("/run/media", "/media", "/mnt")
_WINDOWS_LIBRARY_SUBDIRS = (
    r"Program Files (x86)\Steam", r"Program Files\Steam", "Steam", "SteamLibrary",
)


def _find_steam_root_windows():
    for hive_const, subkey, value_name in _WINDOWS_STEAM_REGISTRY_KEYS:
        hive = hive_const or winreg.HKEY_CURRENT_USER
        # HKCU only has the SteamPath entry; the other two are HKLM.
        hives_to_try = (winreg.HKEY_CURRENT_USER,) if value_name == "SteamPath" else (winreg.HKEY_LOCAL_MACHINE,)
        for h in hives_to_try:
            try:
                with winreg.OpenKey(h, subkey) as key:
                    path, _ = winreg.QueryValueEx(key, value_name)
                if path and os.path.isdir(path):
                    return path
            except OSError:
                continue
    for candidate in _WINDOWS_STEAM_FALLBACK_PATHS:
        if os.path.isdir(candidate):
            return candidate
    return None


def _find_steam_root():
    if IS_WINDOWS:
        return _find_steam_root_windows()
    for candidate in _STEAM_ROOT_CANDIDATES:
        path = os.path.expanduser(candidate)
        if os.path.isdir(path):
            return path
    return None


def _has_dota(library_path):
    return os.path.isdir(os.path.join(library_path, "steamapps", "common", "dota 2 beta"))


def _find_dota_under(path, max_depth=5):
    """Depth-limited search for a Steam-library-shaped folder under `path`.
    Checks `path` itself before recursing, so it short-circuits as soon as
    a match is found instead of walking whole game install trees."""
    try:
        if _has_dota(path):
            return path
        if max_depth <= 0:
            return None
        with os.scandir(path) as entries:
            for entry in entries:
                if entry.name.startswith(".") or not entry.is_dir(follow_symlinks=False):
                    continue
                found = _find_dota_under(entry.path, max_depth - 1)
                if found:
                    return found
    except OSError:
        pass
    return None


def _scan_mounts_for_dota():
    if IS_WINDOWS:
        import string
        for letter in string.ascii_uppercase:
            drive = f"{letter}:\\"
            if not os.path.isdir(drive):
                continue
            for sub in _WINDOWS_LIBRARY_SUBDIRS:
                found = _find_dota_under(os.path.join(drive, sub), max_depth=2)
                if found:
                    return found
        return None

    user = os.environ.get("USER") or os.environ.get("LOGNAME") or ""
    roots = []
    for base in _EXTRA_MOUNT_ROOTS:
        if user:
            roots.append(os.path.join(base, user))
        roots.append(base)
    seen = set()
    for root in roots:
        if root in seen or not os.path.isdir(root):
            continue
        seen.add(root)
        found = _find_dota_under(root)
        if found:
            return found
    return None


def find_dota_library():
    """Returns the Steam library folder that actually has Dota 2 installed
    (i.e. `<this>/steamapps/common/dota 2 beta` exists). Tries, in order:
    every library folder listed in libraryfolders.vdf, Steam's own root,
    then a bounded scan of common external-mount locations (for drives
    Steam itself hasn't been told about, e.g. a manually mounted
    partition, or a drive letter on Windows). Falls back to the old
    hardcoded default if nothing is found anywhere. Never raises."""
    try:
        if os.path.isfile(_OVERRIDE_FILE):
            with open(_OVERRIDE_FILE, "r", encoding="utf-8") as f:
                override = f.read().strip()
            if override and _has_dota(override):
                return override

        root = _find_steam_root()

        if root:
            vdf_path = os.path.join(root, "steamapps", "libraryfolders.vdf")
            if os.path.isfile(vdf_path):
                with open(vdf_path, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
                for library_path in _LIBRARY_PATH_RE.findall(content):
                    library_path = library_path.replace("\\\\", "\\" if IS_WINDOWS else "/")
                    if _has_dota(library_path):
                        return library_path

            if _has_dota(root):
                return root

        mounted = _scan_mounts_for_dota()
        if mounted:
            return mounted

        return root or _DEFAULT
    except Exception:
        return _DEFAULT
