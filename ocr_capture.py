"""Pure OCR pipeline for profile lookup: screen-capture a calibrated
region and read the nickname text out of it. No Qt dependency - safe to
call from a background/pynput thread. Never raises - a failed capture or
unreadable image just means the lookup can't proceed this time, not a
crash (mirrors every other "auxiliary failure is silent" module in this
project: assets.py, opendota_client.py)."""
import os
import subprocess
import sys
import tempfile

import mss
import pytesseract
import requests
from PIL import Image

import event_log
import platform_utils

_IS_LINUX = sys.platform.startswith("linux")

# On Windows, friends installing this app have no system package manager to
# get Tesseract from (unlike Linux, where install.sh's `pacman/apt install
# tesseract` covers it) - without this, OCR-based profile lookup just
# silently returns "" forever with zero indication why. Installed into our
# own data dir (not Program Files), so the NSIS installer's /S silent
# install never needs an admin UAC prompt.
_TESSERACT_INSTALL_DIR = os.path.join(platform_utils.data_dir(), "Tesseract-OCR")
_TESSERACT_EXE = os.path.join(_TESSERACT_INSTALL_DIR, "tesseract.exe")
_tesseract_ready = False


def ensure_tesseract():
    """Idempotent: cheap to call on every OCR attempt. Returns True once
    Tesseract is confirmed callable, False if unavailable and (on Windows)
    the auto-install attempt itself failed - callers should treat False
    the same as "OCR unavailable this run", not raise."""
    global _tesseract_ready
    if _tesseract_ready:
        return True

    already_installed = os.path.isfile(_TESSERACT_EXE) if platform_utils.IS_WINDOWS else True
    if already_installed:
        try:
            if platform_utils.IS_WINDOWS:
                pytesseract.pytesseract.tesseract_cmd = _TESSERACT_EXE
            pytesseract.get_tesseract_version()
            _tesseract_ready = True
            return True
        except Exception:
            pass

    if not platform_utils.IS_WINDOWS:
        # Linux: this is a system package (pacman/apt), same as install.sh
        # already handles - nothing safe to auto-install without sudo.
        event_log.log("ERROR", where="ensure_tesseract", message="tesseract not found in PATH")
        return False

    try:
        api = requests.get(
            "https://api.github.com/repos/UB-Mannheim/tesseract/releases/latest", timeout=15
        )
        api.raise_for_status()
        asset = next(
            a for a in api.json()["assets"] if a["name"].endswith(".exe") and "setup" in a["name"].lower()
        )
        installer_url = asset["browser_download_url"]

        with tempfile.NamedTemporaryFile(suffix=".exe", delete=False) as f:
            installer_path = f.name
            resp = requests.get(installer_url, timeout=180)
            resp.raise_for_status()
            f.write(resp.content)

        # /S = silent, /D=<dir> = install location (must be the LAST arg,
        # no quotes, per NSIS convention) - a non-Program-Files target
        # avoids the UAC prompt a non-technical friend would likely bail
        # out of or not understand.
        subprocess.run(
            [installer_path, "/S", f"/D={_TESSERACT_INSTALL_DIR}"],
            timeout=120, check=True,
        )
        os.unlink(installer_path)

        # The silent installer only ever ships English - language pack
        # selection is GUI-only (confirmed: UB-Mannheim/tesseract#91).
        # read_nickname() asks for "rus+eng", so drop the Russian
        # traineddata in by hand or every Cyrillic nickname reads as "".
        rus_path = os.path.join(_TESSERACT_INSTALL_DIR, "tessdata", "rus.traineddata")
        if not os.path.isfile(rus_path):
            rus_data = requests.get(
                "https://github.com/tesseract-ocr/tessdata/raw/main/rus.traineddata", timeout=60
            )
            rus_data.raise_for_status()
            with open(rus_path, "wb") as f:
                f.write(rus_data.content)

        pytesseract.pytesseract.tesseract_cmd = _TESSERACT_EXE
        pytesseract.get_tesseract_version()
        _tesseract_ready = True
        return True
    except Exception as e:
        event_log.log(
            "ERROR", where="ensure_tesseract_install", exc_type=type(e).__name__, message=str(e)
        )
        return False


def _capture_via_mss(region):
    try:
        with mss.mss() as sct:
            monitor = {
                "left": region["x"], "top": region["y"],
                "width": region["width"], "height": region["height"],
            }
            shot = sct.grab(monitor)
            return Image.frombytes("RGB", shot.size, shot.rgb)
    except Exception as e:
        # mss uses raw X11 calls (XGetImage) under the hood - a native
        # Wayland session is the classic cause of every single grab
        # failing outright (confirmed on a real machine: 15/15 failures,
        # 100%). Silently returning None here (as this always did) made
        # that failure look identical to "OCR just didn't find text" -
        # this log line is what told them apart.
        event_log.log("MSS_CAPTURE_FAILED", exc_type=type(e).__name__, message=str(e))
        return None


def _capture_fullscreen_via_mss():
    try:
        with mss.mss() as sct:
            # monitors[0] is mss's own synthetic "bounding box of every
            # monitor combined" entry - [1] is the actual primary display.
            shot = sct.grab(sct.monitors[1])
            return Image.frombytes("RGB", shot.size, shot.rgb)
    except Exception as e:
        event_log.log("MSS_CAPTURE_FAILED", exc_type=type(e).__name__, message=str(e))
        return None


def capture_fullscreen():
    """Same mss-first, portal-as-Linux-only-fallback strategy as
    capture_region() below, just without a crop - used by
    region_calibrator.py for its full-screen backdrop. Centralized here
    (not duplicated in region_calibrator.py) so there's exactly one place
    that decides when it's safe to reach for the portal."""
    image = _capture_fullscreen_via_mss()
    if image is not None:
        return image
    if not _IS_LINUX:
        return None
    from portal_capture import capture_via_portal
    return capture_via_portal(None)


def capture_region(region):
    image = _capture_via_mss(region)
    if image is not None:
        return image
    if not _IS_LINUX:
        # mss uses native OS APIs on Windows (no X11/Wayland involved at
        # all) - if it failed there, the portal fallback below wouldn't
        # help either (it's a Linux-only, XDG-portal-specific mechanism,
        # and its own dependency - PyGObject/`gi` - isn't even installable
        # the normal way on Windows), so there's nothing further to try.
        return None
    # GNOME Shell's own Screenshot D-Bus interface was tried here first and
    # answered AccessDenied to an arbitrary caller - confirmed on a real
    # GNOME/Wayland session, not just a sandbox quirk. The portal is the
    # one fallback actually proven (live, on real hardware) to return real
    # pixel data under native Wayland. Imported lazily, only reached on
    # Linux, so its `import gi` never runs (and can't fail) on Windows.
    from portal_capture import capture_via_portal
    return capture_via_portal(region)


def read_nickname(image):
    if image is None:
        return ""
    if not ensure_tesseract():
        return ""
    try:
        raw = pytesseract.image_to_string(image, lang="rus+eng")
        lines = [line.strip() for line in raw.splitlines() if line.strip()]
        return lines[0] if lines else ""
    except Exception as e:
        event_log.log("ERROR", where="read_nickname", exc_type=type(e).__name__, message=str(e))
        return ""
