"""Pure OCR pipeline for profile lookup: screen-capture a calibrated
region and read the nickname text out of it. No Qt dependency - safe to
call from a background/pynput thread. Never raises - a failed capture or
unreadable image just means the lookup can't proceed this time, not a
crash (mirrors every other "auxiliary failure is silent" module in this
project: assets.py, opendota_client.py)."""
import sys

import mss
import pytesseract
from PIL import Image

import event_log

_IS_LINUX = sys.platform.startswith("linux")


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
    try:
        raw = pytesseract.image_to_string(image, lang="rus+eng")
        lines = [line.strip() for line in raw.splitlines() if line.strip()]
        return lines[0] if lines else ""
    except Exception:
        return ""
