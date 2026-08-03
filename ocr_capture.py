"""Pure OCR pipeline for profile lookup: screen-capture a calibrated
region and read the nickname text out of it. No Qt dependency - safe to
call from a background/pynput thread. Never raises - a failed capture or
unreadable image just means the lookup can't proceed this time, not a
crash (mirrors every other "auxiliary failure is silent" module in this
project: assets.py, opendota_client.py)."""
import mss
import pytesseract
from PIL import Image

import event_log
from portal_capture import capture_via_portal


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


def capture_region(region):
    image = _capture_via_mss(region)
    if image is not None:
        return image
    # GNOME Shell's own Screenshot D-Bus interface was tried here first and
    # answered AccessDenied to an arbitrary caller - confirmed on a real
    # GNOME/Wayland session, not just a sandbox quirk. The portal is the
    # one fallback actually proven (live, on real hardware) to return real
    # pixel data under native Wayland.
    return capture_via_portal(region)


def read_nickname(image):
    if image is None:
        return ""
    try:
        raw = pytesseract.image_to_string(image, lang="rus+eng")
        lines = [line.strip() for line in raw.splitlines() if line.strip()]
        return lines[0] if lines else ""
    except Exception:
        return ""
