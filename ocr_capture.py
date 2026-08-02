"""Pure OCR pipeline for profile lookup: screen-capture a calibrated
region and read the nickname text out of it. No Qt dependency - safe to
call from a background/pynput thread. Never raises - a failed capture or
unreadable image just means the lookup can't proceed this time, not a
crash (mirrors every other "auxiliary failure is silent" module in this
project: assets.py, opendota_client.py)."""
import mss
import pytesseract
from PIL import Image


def capture_region(region):
    try:
        with mss.mss() as sct:
            monitor = {
                "left": region["x"], "top": region["y"],
                "width": region["width"], "height": region["height"],
            }
            shot = sct.grab(monitor)
            return Image.frombytes("RGB", shot.size, shot.rgb)
    except Exception:
        return None


def read_nickname(image):
    if image is None:
        return ""
    try:
        raw = pytesseract.image_to_string(image, lang="rus+eng")
        lines = [line.strip() for line in raw.splitlines() if line.strip()]
        return lines[0] if lines else ""
    except Exception:
        return ""
