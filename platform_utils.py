"""Small cross-platform helpers - one shared place for the handful of
things that genuinely differ between Linux and Windows, instead of
scattering `sys.platform` checks and OS-specific subprocess calls across
every file that needs one. See also: steam_library.py (Steam/Dota path
detection) and ocr_capture.py (screen capture) for the other two areas
with real per-OS logic - kept in their own files since they're each
substantial on their own, not just a one-liner."""
import os
import subprocess
import sys

IS_WINDOWS = sys.platform == "win32"
IS_LINUX = sys.platform.startswith("linux")

# True when running as a PyInstaller-built .exe (build.bat), False when
# running from plain source (`python3 launcher.py`) - both this project's
# normal Linux usage and Windows dev/testing. PyInstaller sets both of
# these attributes on `sys` itself; they don't exist otherwise.
IS_FROZEN = bool(getattr(sys, "frozen", False))

# Where THIS project's own source files live when run from source - every
# module used to compute this itself via os.path.dirname(__file__), which
# breaks once frozen (that path becomes PyInstaller's onefile temp
# extraction dir, wiped after the process exits - fine for read-only
# bundled assets via resource_path() below, but never for anything that
# needs to persist between runs).
_SOURCE_DIR = os.path.dirname(os.path.abspath(__file__))


def resource_path(*parts):
    """Path to a READ-ONLY bundled asset (a font file, icon.png, the GSI
    .cfg template, ...) - safe to call whether running from source or
    from a frozen .exe. PyInstaller (--add-data) unpacks bundled data into
    sys._MEIPASS at startup; from source, it's just this project's own
    directory."""
    base = sys._MEIPASS if IS_FROZEN else _SOURCE_DIR  # noqa: SLF001 - the documented PyInstaller API for this
    return os.path.join(base, *parts)


def data_dir():
    """Directory for anything this app WRITES and needs to survive to the
    next run - settings JSON, caches, the mod-install manifest. Never
    sys._MEIPASS (wiped after every run of a frozen exe, so anything
    written there would silently vanish next launch) - the exe's own
    folder when frozen (so a portable exe really is portable: drop it
    anywhere, its data travels with it), this project's own source
    directory when running from source (unchanged prior behavior)."""
    if IS_FROZEN:
        d = os.path.dirname(sys.executable)
    else:
        d = _SOURCE_DIR
    os.makedirs(d, exist_ok=True)
    return d


def open_path(path):
    """Opens a file/folder/URL/URI (including a custom protocol link like
    "steam://...") with whatever the OS's own default handler is -
    os.startfile on Windows, xdg-open on Linux. Never raises; a failure
    here just means nothing visibly happens, not a crash."""
    try:
        if IS_WINDOWS:
            os.startfile(path)  # noqa: S606 - always an app-constructed path/URI, never raw user input
        else:
            subprocess.Popen(["xdg-open", path])
    except OSError:
        pass
