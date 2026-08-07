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
import zipfile

import requests

import config
import mod_catalog

DOTA_GAME_DIR = os.path.dirname(config.SERVER_LOG_PATH)
MODS_DIR = os.path.join(DOTA_GAME_DIR, "dota_custom")
LAUNCH_OPTION = "-language custom"

_MANIFEST_PATH = os.path.join(os.path.dirname(__file__), "installed_mods.json")

_session = requests.Session()


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


def _next_pak_names(count):
    """Sequential pakNN_dir.vpk names (10-99 - Valve's own convention for
    add-on VPKs, same range the catalog's README tells manual users to pick
    to avoid conflicts) not already used by any mod we've installed."""
    used = set()
    for entry in _load_manifest().values():
        used.update(entry["files"])
    names = []
    n = 10
    while len(names) < count and n <= 99:
        candidate = f"pak{n:02d}_dir.vpk"
        if candidate not in used:
            names.append(candidate)
            used.add(candidate)
        n += 1
    return names


def _safe_remove(path):
    try:
        os.remove(path)
    except OSError:
        pass


def install_mod(category_id, mod):
    """Downloads mod["file"] (a .vpk, or a .zip containing one/more .vpk),
    writes it into MODS_DIR under a manifest-tracked, collision-free
    pakNN_dir.vpk name. Returns (ok, message)."""
    if is_installed(category_id, mod["name"]):
        return True, "Уже установлен"
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

    vpk_blobs = []
    if mod["file"].lower().endswith(".zip"):
        try:
            with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                for name in zf.namelist():
                    if name.lower().endswith(".vpk"):
                        vpk_blobs.append(zf.read(name))
        except zipfile.BadZipFile:
            return False, "Повреждённый архив мода"
    else:
        vpk_blobs.append(resp.content)

    if not vpk_blobs:
        return False, "В архиве мода не найдено .vpk"

    try:
        os.makedirs(MODS_DIR, exist_ok=True)
    except OSError as exc:
        return False, f"Не удалось создать папку модов: {exc}"

    names = _next_pak_names(len(vpk_blobs))
    if len(names) < len(vpk_blobs):
        return False, "Слишком много установленных модов (лимит pak10-pak99 исчерпан)"

    written = []
    for name, blob in zip(names, vpk_blobs):
        dest = os.path.join(MODS_DIR, name)
        try:
            with open(dest, "wb") as f:
                f.write(blob)
            written.append(name)
        except OSError as exc:
            for w in written:
                _safe_remove(os.path.join(MODS_DIR, w))
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
    for fname in entry["files"]:
        _safe_remove(os.path.join(MODS_DIR, fname))
    _save_manifest(manifest)
    return True, "Удалён"
