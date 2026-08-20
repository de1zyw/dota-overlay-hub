"""Installs/uninstalls cosmetic mods from the Dota2PornFx catalog
(mod_catalog.py) using the exact same mechanism the catalog's own README
documents: drop a .vpk into a custom-language folder inside Dota's game
dir, add "-language <name>" to Dota's Steam launch options. No Steam
registry/localconfig.vdf editing - that's Steam's own live state and far
riskier to automate than a plain file drop, so the launch-option step
stays a one-time manual instruction shown in the UI.

Tracks what WE installed in a local manifest (installed_mods.json) so
"Удалить" only ever touches files this app itself placed, never someone's
own hand-installed mods that happen to share the folder."""
import io
import json
import os
import shutil
import zipfile

import requests

import config
import mod_catalog
import mod_language_settings
import platform_utils

DOTA_GAME_DIR = os.path.dirname(config.SERVER_LOG_PATH)  # .../dota 2 beta/game/dota
# dota_<language> add-on folders are siblings of "dota" itself, directly
# under "game" - confirmed against a real install (game/dota_russian,
# game/dota_lv, game/dota_schinese all sit next to game/dota, none of them
# nested inside it). An earlier version of this file put MODS_DIR one
# level too deep (inside game/dota/) - real installs made through that
# version never actually worked, Dota was never looking there.
_ADDON_ROOT_DIR = os.path.dirname(DOTA_GAME_DIR)  # .../dota 2 beta/game

_MANIFEST_PATH = os.path.join(platform_utils.data_dir(), "installed_mods.json")

_session = requests.Session()

# "cursors" and "fonts" aren't packed into pakNN_dir.vpk at all - their
# catalog zips ship raw loose files (a full cursor.ani/.bmp/.res set, or 4
# named .ttf/.otf files) that the catalog's own Windows Install.bat just
# copies into a FIXED subfolder of game/dota itself - confirmed by reading
# those .bat files directly rather than guessing. Not -language-slot
# dependent at all (applies regardless of which -language is active),
# unlike every pakNN-based category. zip_subdir is matched by suffix
# against each zip entry's path (the top-level folder is named after the
# mod itself, e.g. "Earthshaker Cursor/cursor/...").
LOOSE_FILE_CATEGORIES = {
    "cursors": {"zip_subdir": "cursor", "dest_subdir": os.path.join("resource", "cursor")},
    "fonts": {"zip_subdir": "assets/custom", "dest_subdir": os.path.join("panorama", "fonts")},
}

_BACKUP_ROOT = os.path.join(platform_utils.data_dir(), ".loose_mod_backups")


def is_loose_file_category(category_id):
    return category_id in LOOSE_FILE_CATEGORIES


def get_language():
    return mod_language_settings.load()


def get_mods_dir(language=None):
    """The dota_<language> folder mods actually get written to - a
    function, not a constant, so changing the language setting (see
    set_language()) takes effect immediately without an app restart."""
    return os.path.join(_ADDON_ROOT_DIR, f"dota_{language or get_language()}")


def get_launch_option(language=None):
    return f"-language {language or get_language()}"


def set_language(new_language, migrate=True):
    """Switches the -language slot the МОДЫ tab installs into. If
    `migrate` is True (the default), every file this app has ever
    installed is physically moved from the OLD dota_<language> folder to
    the new one - without this, is_installed()/uninstall_mod() would keep
    reporting old installs as present while actually looking in the wrong
    (new) folder, and Dota would stop seeing them under the new -language
    launch option too. Returns (ok, message)."""
    if not mod_language_settings.is_valid(new_language):
        return False, "Недопустимое имя (буквы/цифры/дефис/подчёркивание, до 32 символов)"
    old_language = get_language()
    if new_language == old_language:
        return True, "Без изменений"

    if migrate:
        old_dir = get_mods_dir(old_language)
        new_dir = get_mods_dir(new_language)
        manifest = _load_manifest()
        all_files = [f for entry in manifest.values() for f in entry["files"]]
        if all_files:
            try:
                os.makedirs(new_dir, exist_ok=True)
            except OSError as exc:
                return False, f"Не удалось создать новую папку: {exc}"
            moved = []
            for fname in all_files:
                src = os.path.join(old_dir, fname)
                if not os.path.exists(src):
                    continue
                dest = os.path.join(new_dir, fname)
                try:
                    # fname can be a relative subpath ("maps/dota.vpk"),
                    # not just a bare filename - its parent under new_dir
                    # isn't guaranteed to exist yet.
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    shutil.move(src, dest)
                    moved.append(fname)
                except OSError as exc:
                    for m in moved:
                        _safe_move_back(os.path.join(new_dir, m), os.path.join(old_dir, m))
                    return False, f"Не удалось перенести {fname}: {exc}"

    if not mod_language_settings.save(new_language):
        return False, "Не удалось сохранить настройку"
    return True, f"Готово — теперь моды ставятся в dota_{new_language}"


def _safe_move_back(src, dst):
    try:
        shutil.move(src, dst)
    except OSError:
        pass


def dota_found():
    return os.path.isdir(DOTA_GAME_DIR)


def _load_manifest():
    if not os.path.exists(_MANIFEST_PATH):
        return {}
    try:
        with open(_MANIFEST_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def _save_manifest(manifest):
    tmp_path = f"{_MANIFEST_PATH}.tmp{os.getpid()}"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, _MANIFEST_PATH)
    except OSError:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


def _mod_key(category_id, mod_name):
    return f"{category_id}::{mod_name}"


def is_installed(category_id, mod_name):
    return _mod_key(category_id, mod_name) in _load_manifest()


def list_installed():
    return _load_manifest()


def scan_installed():
    """Reconciles the manifest against what's actually in the mods folder
    right now - the manifest is normally kept in sync automatically
    (install/uninstall both update it), but nothing stops a user from
    deleting a mod's files by hand outside the app, or (rarer) losing a
    write partway through. Returns (stale_keys, orphan_files):
    - stale_keys: manifest entries where ANY of their tracked files are
      missing from disk - shown to the user as "no longer really
      installed", offered as one-click removal from the manifest.
    - orphan_files: pakNN-named .vpk files sitting in the mods folder that
      no manifest entry references - not touched automatically (could be
      dota2-minify's own output, or something the user placed by hand),
      just surfaced so it's not a silent mystery."""
    manifest = _load_manifest()
    mods_dir = get_mods_dir()

    stale_keys = []
    tracked_files = set()
    for key, entry in manifest.items():
        for fname in entry["files"]:
            tracked_files.add(fname)
            full_path = os.path.join(mods_dir, fname)
            if not os.path.isfile(full_path):
                stale_keys.append(key)
                break

    orphan_files = []
    try:
        for fname in os.listdir(mods_dir):
            if fname.lower().endswith(".vpk") and fname not in tracked_files:
                orphan_files.append(fname)
    except OSError:
        pass

    return stale_keys, sorted(orphan_files)


def remove_stale_entries(keys):
    """Drops manifest entries scan_installed() flagged as stale (files
    already gone from disk) - doesn't touch any file, there's nothing
    left to remove, just stops the app claiming they're still installed."""
    manifest = _load_manifest()
    for key in keys:
        manifest.pop(key, None)
    _save_manifest(manifest)


def _used_filenames():
    """Every pakNN_dir/pakNN_NNN.vpk name that must NOT be picked for a
    new install - our own manifest, PLUS whatever .vpk files already
    physically sit in the mods folder right now. The disk scan matters
    because that folder isn't exclusively ours: dota2-minify (if the user
    has it, and it's configured to output to this same language slot -
    see mod_language_settings.detect_minify_language()) compiles its own
    mods into pak files there too, and hardcoding "Minify uses pakXX"
    would silently break the moment Minify's own numbering changes -
    checking the real directory contents never goes stale."""
    used = set()
    for entry in _load_manifest().values():
        used.update(entry["files"])
    mods_dir = get_mods_dir()
    try:
        used.update(f for f in os.listdir(mods_dir) if f.lower().endswith(".vpk"))
    except OSError:
        pass
    return used


def _next_pak_names(count):
    """Sequential pakNN_dir.vpk names (10-99 - Valve's own convention for
    add-on VPKs, same range the catalog's README tells manual users to pick
    to avoid conflicts) not already used by any mod we've installed."""
    used = _used_filenames()
    names = []
    n = 10
    while len(names) < count and n <= 99:
        candidate = f"pak{n:02d}_dir.vpk"
        if candidate not in used:
            names.append(candidate)
            used.add(candidate)
        n += 1
    return names


def _next_free_prefix(suffixes):
    """Finds a "pakNN" prefix (10-99) where NONE of the given suffixes
    (e.g. ["_dir.vpk", "_000.vpk"] for a chunked merge output) collide
    with an already-installed filename - used for mod_tools.py output,
    which arrives as a whole file GROUP that must move together under one
    freshly chosen number, never split across several."""
    used = _used_filenames()
    n = 10
    while n <= 99:
        prefix = f"pak{n:02d}"
        if not any(f"{prefix}{suffix}" in used for suffix in suffixes):
            return prefix
        n += 1
    return None


def _safe_remove(path):
    try:
        os.remove(path)
    except OSError:
        pass


def fetch_mod_vpk_blobs(category_id, mod):
    """Download + unzip step of install_mod, pulled out on its own so the
    cart's merge-into-one-pak path (cart_dialog.py, mods above the "ask to
    merge" threshold) can get raw .vpk bytes for several mods before
    deciding how to write any of them to disk - install_mod itself still
    does download+write as one step for the normal (non-merge) path.
    Returns (ok, map_blob_or_None, vpk_blobs, message)."""
    url = mod_catalog.get_download_url(category_id, mod.get("file"))
    if not url:
        return False, None, [], "У этого мода нет файла для скачивания"

    try:
        resp = _session.get(url, timeout=60)
        resp.raise_for_status()
    except requests.exceptions.RequestException as exc:
        return False, None, [], f"Ошибка скачивания: {exc}"

    # Terrain/map replacements ship as maps/dota.vpk inside the zip - NOT
    # a pakNN addon. Confirmed via the catalog's own install guide: it
    # goes straight into the same per-language folder as everything else,
    # just under a maps/ subfolder with a fixed filename (Dota's own VPK
    # search path checks there too) - never renamed/numbered, and only
    # one map replacement can be active at a time (fixed filename, same
    # "last one wins" as installing it by hand twice).
    map_blob = None
    vpk_blobs = []
    if mod["file"].lower().endswith(".zip"):
        try:
            with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                for name in zf.namelist():
                    lname = name.lower()
                    if lname == "maps/dota.vpk" or lname.endswith("/maps/dota.vpk"):
                        map_blob = zf.read(name)
                    elif lname.endswith(".vpk"):
                        vpk_blobs.append(zf.read(name))
        except zipfile.BadZipFile:
            return False, None, [], "Повреждённый архив мода"
    else:
        vpk_blobs.append(resp.content)
    return True, map_blob, vpk_blobs, ""


def install_mod(category_id, mod):
    """Downloads mod["file"] (a .vpk, or a .zip containing one/more .vpk),
    writes it into MODS_DIR under a manifest-tracked, collision-free
    pakNN_dir.vpk name. Returns (ok, message)."""
    if is_installed(category_id, mod["name"]):
        return True, "Уже установлен"
    if not dota_found():
        return False, "Папка Dota 2 не найдена"

    ok, map_blob, vpk_blobs, message = fetch_mod_vpk_blobs(category_id, mod)
    if not ok:
        return False, message

    mods_dir = get_mods_dir()

    if map_blob is not None:
        map_dest_dir = os.path.join(mods_dir, "maps")
        try:
            os.makedirs(map_dest_dir, exist_ok=True)
            with open(os.path.join(map_dest_dir, "dota.vpk"), "wb") as f:
                f.write(map_blob)
        except OSError as exc:
            return False, f"Ошибка записи: {exc}"

        key = _mod_key(category_id, mod["name"])
        manifest = _load_manifest()
        for existing_key in [k for k, v in manifest.items() if v.get("map") and k != key]:
            manifest.pop(existing_key, None)
        manifest[key] = {
            "category": category_id, "name": mod["name"],
            "files": [os.path.join("maps", "dota.vpk")], "map": True,
        }
        _save_manifest(manifest)
        return True, "Установлен"

    if not vpk_blobs:
        return False, "В архиве мода не найдено .vpk"
    try:
        os.makedirs(mods_dir, exist_ok=True)
    except OSError as exc:
        return False, f"Не удалось создать папку модов: {exc}"

    names = _next_pak_names(len(vpk_blobs))
    if len(names) < len(vpk_blobs):
        return False, "Слишком много установленных модов (лимит pak10-pak99 исчерпан)"

    written = []
    for name, blob in zip(names, vpk_blobs):
        dest = os.path.join(mods_dir, name)
        try:
            with open(dest, "wb") as f:
                f.write(blob)
            written.append(name)
        except OSError as exc:
            for w in written:
                _safe_remove(os.path.join(mods_dir, w))
            return False, f"Ошибка записи: {exc}"

    manifest = _load_manifest()
    manifest[_mod_key(category_id, mod["name"])] = {
        "category": category_id, "name": mod["name"], "files": written,
    }
    _save_manifest(manifest)
    return True, "Установлен"


def uninstall_mod(category_id, mod_name):
    key = _mod_key(category_id, mod_name)
    manifest = _load_manifest()
    entry = manifest.pop(key, None)
    if entry is None:
        return True, "Не был установлен"
    mods_dir = get_mods_dir()
    for fname in entry["files"]:
        _safe_remove(os.path.join(mods_dir, fname))
    _save_manifest(manifest)
    return True, "Удалён"


def install_from_files(category_id, display_name, source_paths):
    """Adopts already-built .vpk file(s) - e.g. mod_tools.py's pack/merge/
    background-changer output - into MODS_DIR under one manifest-tracked,
    collision-free pak group. Unlike install_mod, there's no download step;
    the files already exist locally and are only copied (source_paths are
    never touched/moved)."""
    if not dota_found():
        return False, "Папка Dota 2 не найдена"
    if not source_paths:
        return False, "Нет файлов для установки"
    mods_dir = get_mods_dir()
    try:
        os.makedirs(mods_dir, exist_ok=True)
    except OSError as exc:
        return False, f"Не удалось создать папку модов: {exc}"

    suffixes = [f"_{os.path.basename(p).split('_', 1)[1]}" for p in source_paths]
    new_prefix = _next_free_prefix(suffixes)
    if new_prefix is None:
        return False, "Слишком много установленных модов (лимит pak10-pak99 исчерпан)"

    written = []
    for path, suffix in zip(source_paths, suffixes):
        new_name = f"{new_prefix}{suffix}"
        dest = os.path.join(mods_dir, new_name)
        try:
            shutil.copy2(path, dest)
            written.append(new_name)
        except OSError as exc:
            for w in written:
                _safe_remove(os.path.join(mods_dir, w))
            return False, f"Ошибка записи: {exc}"

    manifest = _load_manifest()
    manifest[_mod_key(category_id, display_name)] = {
        "category": category_id, "name": display_name, "files": written,
    }
    _save_manifest(manifest)
    return True, "Установлен"


def install_loose_mod(category_id, mod):
    """Cursors/fonts: extract the zip's loose files (not a .vpk) straight
    into a fixed subfolder of game/dota - see LOOSE_FILE_CATEGORIES'
    comment for why. Whatever's already in that destination (a previous
    mod from this same category, or nothing - Dota's real defaults live
    safely packed inside its own VPKs, never touched) is backed up first
    so uninstall can put it back exactly."""
    spec = LOOSE_FILE_CATEGORIES.get(category_id)
    if spec is None:
        raise ValueError(f"{category_id} is not a loose-file category")
    if not dota_found():
        return False, "Папка Dota 2 не найдена"

    url = mod_catalog.get_download_url(category_id, mod.get("file"))
    if not url:
        return False, "У этого мода нет файла для скачивания"
    try:
        resp = _session.get(url, timeout=60)
        resp.raise_for_status()
    except requests.exceptions.RequestException as exc:
        return False, f"Ошибка скачивания: {exc}"

    zip_subdir = spec["zip_subdir"].replace("\\", "/")
    dest_dir = os.path.join(DOTA_GAME_DIR, spec["dest_subdir"])

    try:
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            marker = f"/{zip_subdir}/"
            payload = {}
            for name in zf.namelist():
                if name.endswith("/") or marker not in f"/{name}":
                    continue
                fname = os.path.basename(name)
                if fname:
                    payload[fname] = zf.read(name)
    except zipfile.BadZipFile:
        return False, "Повреждённый архив мода"

    if not payload:
        return False, f"В архиве не найдена папка {spec['zip_subdir']}"

    backup_dir = os.path.join(_BACKUP_ROOT, category_id)
    already_backed_up = os.path.isdir(backup_dir) and os.listdir(backup_dir)
    try:
        os.makedirs(dest_dir, exist_ok=True)
        if not already_backed_up:
            os.makedirs(backup_dir, exist_ok=True)
            for fname in os.listdir(dest_dir):
                src = os.path.join(dest_dir, fname)
                if os.path.isfile(src):
                    shutil.copy2(src, os.path.join(backup_dir, fname))
    except OSError as exc:
        return False, f"Не удалось подготовить папку: {exc}"

    written = []
    try:
        for fname, data in payload.items():
            with open(os.path.join(dest_dir, fname), "wb") as f:
                f.write(data)
            written.append(fname)
    except OSError as exc:
        return False, f"Ошибка записи: {exc}"

    manifest = _load_manifest()
    # Only one loose mod can be "active" per category at a time (same
    # destination folder, last-one-wins - identical to what the real
    # Windows installer does if you run it twice) - drop any previous
    # entry from this category so a stale "Удалить" doesn't target files
    # that no longer belong to it.
    for existing_key in [
        k for k, v in manifest.items()
        if v.get("category") == category_id and v.get("loose")
    ]:
        manifest.pop(existing_key, None)

    manifest[_mod_key(category_id, mod["name"])] = {
        "category": category_id, "name": mod["name"], "files": written, "loose": True,
    }
    _save_manifest(manifest)
    return True, "Установлен"


def uninstall_loose_mod(category_id, mod_name):
    spec = LOOSE_FILE_CATEGORIES.get(category_id)
    if spec is None:
        raise ValueError(f"{category_id} is not a loose-file category")
    key = _mod_key(category_id, mod_name)
    manifest = _load_manifest()
    entry = manifest.pop(key, None)
    if entry is None:
        return True, "Не был установлен"

    dest_dir = os.path.join(DOTA_GAME_DIR, spec["dest_subdir"])
    for fname in entry["files"]:
        _safe_remove(os.path.join(dest_dir, fname))

    backup_dir = os.path.join(_BACKUP_ROOT, category_id)
    if os.path.isdir(backup_dir):
        for fname in os.listdir(backup_dir):
            try:
                shutil.move(os.path.join(backup_dir, fname), os.path.join(dest_dir, fname))
            except OSError:
                pass
        try:
            os.rmdir(backup_dir)
        except OSError:
            pass

    _save_manifest(manifest)
    return True, "Удалён"
