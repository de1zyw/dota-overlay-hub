"""Screenshot capture via the XDG Desktop Portal (org.freedesktop.portal.Screenshot) -
the sanctioned, Wayland-safe way to grab screen content. Needs a one-time system
"Allow Apps to Take Screenshots?" permission grant (persists afterwards, same model as
camera/mic/location permissions) - shown automatically on the first call, not something
the app has to prompt for itself.

Exists because, on a real GNOME/Wayland session (confirmed live, not just theorized):
mss's raw X11 grab (XGetImage) sees nothing at all, and GNOME Shell's own screenshot
D-Bus interface (org.gnome.Shell.Screenshot.ScreenshotArea) answers AccessDenied to an
arbitrary caller - this portal is the one path that actually returns real pixel data.
"""
import os
import uuid
from urllib.parse import unquote, urlparse

import gi

gi.require_version("GLib", "2.0")
from gi.repository import Gio, GLib
from PIL import Image

import event_log


def capture_via_portal(region=None, timeout_s=8):
    """region: optional {"x","y","width","height"} to crop to; None returns the
    full screenshot as-is (used by the calibrator's fullscreen backdrop)."""
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        conn_name = bus.get_unique_name().lstrip(":").replace(".", "_")
        token = "overlay" + uuid.uuid4().hex[:8]
        handle_path = f"/org/freedesktop/portal/desktop/request/{conn_name}/{token}"

        result = {}
        loop = GLib.MainLoop()

        def on_signal(connection, sender, path, iface, signal, params, user_data):
            result["code"], result["results"] = params.unpack()
            loop.quit()

        sub_id = bus.signal_subscribe(
            "org.freedesktop.portal.Desktop",
            "org.freedesktop.portal.Request",
            "Response",
            handle_path,
            None,
            Gio.DBusSignalFlags.NONE,
            on_signal,
            None,
        )

        options = {
            "handle_token": GLib.Variant("s", token),
            "interactive": GLib.Variant("b", False),
        }
        bus.call_sync(
            "org.freedesktop.portal.Desktop",
            "/org/freedesktop/portal/desktop",
            "org.freedesktop.portal.Screenshot",
            "Screenshot",
            GLib.Variant("(sa{sv})", ("", options)),
            GLib.VariantType("(o)"),
            Gio.DBusCallFlags.NONE,
            -1,
            None,
        )

        GLib.timeout_add_seconds(timeout_s, loop.quit)
        loop.run()
        bus.signal_unsubscribe(sub_id)

        if result.get("code") != 0:
            event_log.log(
                "PORTAL_CAPTURE_FAILED",
                reason="denied_cancelled_or_timed_out",
                code=result.get("code"),
            )
            return None
        uri = result.get("results", {}).get("uri")
        if not uri:
            event_log.log("PORTAL_CAPTURE_FAILED", reason="no_uri")
            return None

        path = unquote(urlparse(uri).path)
        try:
            with Image.open(path) as raw:
                img = raw.convert("RGB")
                if region is not None:
                    img = img.crop((
                        region["x"], region["y"],
                        region["x"] + region["width"], region["y"] + region["height"],
                    ))
                img.load()
        finally:
            if os.path.exists(path):
                os.unlink(path)
        return img
    except Exception as e:
        event_log.log("PORTAL_CAPTURE_FAILED", exc_type=type(e).__name__, message=str(e))
        return None
