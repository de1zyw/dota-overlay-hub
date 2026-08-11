"""Console-only companion tools from the Dota2PornFx ecosystem
(github.com/h6rd) - VPKTool (pack/unpack .vpk), VPKMerge (combine several
.vpk into one), and Background Changer (build a custom main-menu
background .vpk from your own video or photo). All three are plain CLI
binaries with no GUI - confirmed by hand (real runs against real files)
before wiring this up: each auto-detects what to do from its own current
working directory and prints plain text, no prompts, no window.

VPKTool/VPKMerge/Create all DELETE (move to trash) their source files
after a successful run, by their own documented design - every function
here stages a private COPY in a throwaway temp dir first, so the caller's
original files are never touched, let alone at risk."""
import io
import os
import re
import shutil
import stat
import subprocess
import tempfile
import zipfile

import requests

import mod_catalog
import platform_utils

CACHE_DIR = os.path.join(platform_utils.data_dir(), ".mod_tools_cache")
os.makedirs(CACHE_DIR, exist_ok=True)

_session = requests.Session()

# VPKTool/VPKMerge ship as one lean CLI .exe per platform (same repo, same
# auto-detect-from-cwd behavior confirmed by their file size/packaging
# pattern matching the Linux CLI build) - only the download URL and binary
# extension differ. Background Changer does NOT get the same treatment:
# its Windows build (Changer.exe, ~32MB, bundles its own ffmpeg.exe) is a
# real GUI application, unlike the Linux build's two scriptable CLI
# binaries (Convert/Create) - confirmed by actually downloading and
# inspecting both zips, not assumed. There is no command-line workflow to
# automate on Windows, so create_background() is Linux-only by design,
# not an oversight - see its own docstring.
if platform_utils.IS_WINDOWS:
    _VPKTOOL_URL = "https://github.com/h6rd/VPKTool/releases/latest/download/VPKTool-Win.zip"
    _VPKMERGE_URL = "https://github.com/h6rd/VPKMerge/releases/latest/download/VPKMerge-Win.zip"
    _VPKTOOL_BIN_NAME = "VPKTool.exe"
    _VPKMERGE_BIN_NAME = "VPKMerge.exe"
else:
    _VPKTOOL_URL = "https://github.com/h6rd/VPKTool/releases/latest/download/VPKTool-Linux.zip"
    _VPKMERGE_URL = "https://github.com/h6rd/VPKMerge/releases/latest/download/VPKMerge-Linux.zip"
    _VPKTOOL_BIN_NAME = "VPKTool"
    _VPKMERGE_BIN_NAME = "VPKMerge"
_BACKGROUND_CHANGER_URL = (
    f"{mod_catalog.REPO_BASE}/assets/files/tools/Background%20Changer%20Linux.zip"
)

_DIR_VPK_RE = re.compile(r"^pak\d+_dir\.vpk$", re.IGNORECASE)


class ToolError(Exception):
    pass


def _download_and_extract(url, cache_name):
    dest = os.path.join(CACHE_DIR, cache_name)
    if os.path.isdir(dest):
        return dest
    try:
        resp = _session.get(url, timeout=120)
        resp.raise_for_status()
    except requests.exceptions.RequestException as exc:
        raise ToolError(f"Не удалось скачать {cache_name}: {exc}") from exc
    extract_tmp = f"{dest}.tmp{os.getpid()}"
    try:
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            zf.extractall(extract_tmp)
        os.replace(extract_tmp, dest)
    except (zipfile.BadZipFile, OSError) as exc:
        shutil.rmtree(extract_tmp, ignore_errors=True)
        raise ToolError(f"Повреждённый архив {cache_name}: {exc}") from exc
    return dest


def _make_executable(path):
    # The +x bit is meaningless on Windows (a .exe runs by extension, not
    # permission bit) - os.chmod there wouldn't error, but there's nothing
    # for it to actually do, so skip it rather than pretend it matters.
    if platform_utils.IS_WINDOWS:
        return
    st = os.stat(path)
    os.chmod(path, st.st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def _get_vpktool():
    root = _download_and_extract(_VPKTOOL_URL, "VPKTool")
    binary = os.path.join(root, "VPKTool", _VPKTOOL_BIN_NAME)
    if not os.path.isfile(binary):
        raise ToolError("VPKTool: бинарник не найден после распаковки")
    _make_executable(binary)
    return binary


def _get_vpkmerge():
    root = _download_and_extract(_VPKMERGE_URL, "VPKMerge")
    binary = os.path.join(root, "VPKMerge", _VPKMERGE_BIN_NAME)
    if not os.path.isfile(binary):
        raise ToolError("VPKMerge: бинарник не найден после распаковки")
    _make_executable(binary)
    return binary


def _get_background_changer_template():
    if platform_utils.IS_WINDOWS:
        # The Windows build (Changer.exe + bundled ffmpeg.exe) is a real
        # GUI app, unlike Linux's scriptable Convert/Create CLI pair -
        # confirmed by downloading and inspecting both zips, nothing to
        # automate here. create_background() checks this same flag before
        # ever reaching this function; this guard is a second layer, not
        # the primary gate, in case it's ever called some other way.
        raise ToolError(
            "На Windows это GUI-программа (Changer.exe), автоматический запуск недоступен — "
            "скачай и запусти вручную с сайта каталога"
        )
    root = _download_and_extract(_BACKGROUND_CHANGER_URL, "BackgroundChanger")
    template = os.path.join(root, "Background Changer")
    if not os.path.isdir(template):
        raise ToolError("Background Changer: содержимое архива не распознано")
    return template


def _run(binary, cwd, timeout=180):
    try:
        result = subprocess.run(
            [binary], cwd=cwd, capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise ToolError("Инструмент завис — превышено время ожидания") from exc
    except OSError as exc:
        raise ToolError(f"Не удалось запустить инструмент: {exc}") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "неизвестная ошибка").strip()
        raise ToolError(detail[-500:])
    return result.stdout


def _collect_pak_group(staging_dir):
    """Finds the pakNN_dir.vpk a run just produced, plus every sibling
    chunk file sharing that exact "pakNN" prefix. VPKMerge/large outputs
    split into pakNN_dir.vpk + pakNN_000.vpk + ... - the dir file expects
    its chunks to share its own numeric prefix, so callers must always
    move/rename the whole group together, never one file at a time."""
    dir_files = [f for f in os.listdir(staging_dir) if _DIR_VPK_RE.match(f)]
    if not dir_files:
        raise ToolError("Инструмент не создал .vpk файл")
    dir_file = dir_files[0]
    prefix = dir_file[: dir_file.index("_dir.vpk")]
    group = sorted(
        f for f in os.listdir(staging_dir)
        if f.startswith(f"{prefix}_") and f.lower().endswith(".vpk")
    )
    return [os.path.join(staging_dir, f) for f in group]


def _move_group_to(staging_dir, group, output_dir):
    os.makedirs(output_dir, exist_ok=True)
    result = []
    for path in group:
        dst = os.path.join(output_dir, os.path.basename(path))
        shutil.move(path, dst)
        result.append(dst)
    return result


def unpack_vpk(vpk_path, output_dir):
    """Extracts a .vpk's contents into output_dir. vpk_path itself is
    never touched - a copy is staged and operated on instead."""
    binary = _get_vpktool()
    with tempfile.TemporaryDirectory(prefix="vpktool-unpack-") as staging:
        shutil.copy2(vpk_path, os.path.join(staging, os.path.basename(vpk_path)))
        _run(binary, cwd=staging)
        os.makedirs(output_dir, exist_ok=True)
        extracted = []
        for name in os.listdir(staging):
            if name == os.path.basename(vpk_path):
                continue
            src = os.path.join(staging, name)
            dst = os.path.join(output_dir, name)
            if os.path.isdir(dst):
                shutil.rmtree(dst)
            elif os.path.exists(dst):
                os.remove(dst)
            shutil.move(src, dst)
            extracted.append(dst)
        if not extracted:
            raise ToolError("VPKTool не извлёк ни одного файла")
        return extracted


def pack_to_vpk(input_dir, output_dir):
    """Packs every file/folder inside input_dir into one new .vpk, written
    into output_dir. input_dir's own contents are copied, never moved."""
    binary = _get_vpktool()
    entries = os.listdir(input_dir)
    if not entries:
        raise ToolError("Папка пуста")
    with tempfile.TemporaryDirectory(prefix="vpktool-pack-") as staging:
        for name in entries:
            src = os.path.join(input_dir, name)
            dst = os.path.join(staging, name)
            (shutil.copytree if os.path.isdir(src) else shutil.copy2)(src, dst)
        _run(binary, cwd=staging)
        group = _collect_pak_group(staging)
        return _move_group_to(staging, group, output_dir)


def merge_vpks(vpk_paths, output_dir):
    """Merges 2+ .vpk files into one (possibly multi-file: pakNN_dir.vpk
    plus pakNN_000.vpk chunk files for larger merges), written into
    output_dir."""
    if len(vpk_paths) < 2:
        raise ToolError("Нужно минимум 2 файла для объединения")
    binary = _get_vpkmerge()
    with tempfile.TemporaryDirectory(prefix="vpkmerge-") as staging:
        for path in vpk_paths:
            shutil.copy2(path, os.path.join(staging, os.path.basename(path)))
        _run(binary, cwd=staging, timeout=300)
        group = _collect_pak_group(staging)
        return _move_group_to(staging, group, output_dir)


def background_changer_available():
    # Windows' build is a GUI app (Changer.exe) with no CLI workflow to
    # automate at all - "unavailable" regardless of ffmpeg, which is only
    # even relevant to the Linux CLI pair (Convert shells out to it).
    if platform_utils.IS_WINDOWS:
        return False
    return shutil.which("ffmpeg") is not None


def create_background(media_path, output_dir):
    """Builds a custom main-menu background .vpk from a user-supplied
    video or photo (media_path), written into output_dir. Linux-only -
    needs system ffmpeg (the bundled Convert binary shells out to it, same
    requirement the tool's own guide.txt documents); on Windows the same
    feature is a GUI-only app (Changer.exe), nothing to script here."""
    if platform_utils.IS_WINDOWS:
        raise ToolError(
            "На Windows это GUI-программа (Changer.exe), автоматический запуск недоступен — "
            "скачай и запусти вручную с сайта каталога"
        )
    if not background_changer_available():
        raise ToolError(
            "Нужен ffmpeg (Background Changer использует его для конвертации). "
            "Установи через пакетный менеджер твоего дистрибутива (например: sudo pacman -S ffmpeg)"
        )
    template = _get_background_changer_template()
    with tempfile.TemporaryDirectory(prefix="bgchanger-") as staging:
        work = os.path.join(staging, "work")
        shutil.copytree(template, work)
        convert_bin = os.path.join(work, "Convert", "Convert")
        create_bin = os.path.join(work, "Create")
        if not os.path.isfile(convert_bin) or not os.path.isfile(create_bin):
            raise ToolError("Background Changer: бинарники не найдены после распаковки")
        _make_executable(convert_bin)
        _make_executable(create_bin)

        shutil.copy2(
            media_path, os.path.join(work, "Convert", os.path.basename(media_path))
        )
        _run(convert_bin, cwd=os.path.join(work, "Convert"), timeout=300)
        _run(create_bin, cwd=work, timeout=120)

        group = _collect_pak_group(work)
        return _move_group_to(work, group, output_dir)
