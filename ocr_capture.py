"""Pure OCR pipeline for profile lookup: screen-capture a calibrated
region and read the nickname text out of it. No Qt dependency - safe to
call from a background/pynput thread. Never raises - a failed capture or
unreadable image just means the lookup can't proceed this time, not a
crash (mirrors every other "auxiliary failure is silent" module in this
project: assets.py, opendota_client.py)."""
import os
import subprocess
import tempfile

import mss
import pytesseract
from PIL import Image

import event_log


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


def _capture_via_gnome_shell(region):
    """Fallback for GNOME on Wayland, where mss can't see anything at all.
    GNOME Shell (the compositor itself, not an external app) exposes its
    own screenshot D-Bus interface - the same one behind the PrintScreen
    key - which can grab an arbitrary region by coordinates directly, with
    no interactive permission dialog (unlike the freedesktop portal's
    Screenshot API) and no extra package to install: `gdbus` ships with
    glib2, which is already a hard dependency of GNOME Shell itself."""
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp_path = tmp.name
        result = subprocess.run(
            [
                "gdbus", "call", "--session",
                "--dest", "org.gnome.Shell",
                "--object-path", "/org/gnome/Shell/Screenshot",
                "--method", "org.gnome.Shell.Screenshot.ScreenshotArea",
                str(region["x"]), str(region["y"]),
                str(region["width"]), str(region["height"]),
                "false", tmp_path,
            ],
            capture_output=True, timeout=5, text=True,
        )
        if result.returncode != 0 or "true" not in result.stdout.lower():
            event_log.log(
                "GNOME_SHELL_CAPTURE_FAILED",
                returncode=result.returncode, stdout=result.stdout, stderr=result.stderr,
            )
            return None
        return Image.open(tmp_path).convert("RGB")
    except Exception as e:
        event_log.log("GNOME_SHELL_CAPTURE_FAILED", exc_type=type(e).__name__, message=str(e))
        return None
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)


def capture_region(region):
    image = _capture_via_mss(region)
    if image is not None:
        return image
    return _capture_via_gnome_shell(region)


def read_nickname(image):
    if image is None:
        return ""
    try:
        raw = pytesseract.image_to_string(image, lang="rus+eng")
        lines = [line.strip() for line in raw.splitlines() if line.strip()]
        return lines[0] if lines else ""
    except Exception:
        return ""
