"""Loads the bundled Inter typeface (assets/fonts/) into Qt's font
database. Bundled rather than relying on the system having it installed -
this app ships as a plain script, not a packaged/distro-installed app, so
there's no dependency mechanism to guarantee a font package is present."""
import glob
import os

from PyQt6.QtGui import QFont, QFontDatabase

_FONTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "fonts")
_loaded = False


def load():
    """Registers every bundled Inter weight with Qt's font database. Safe
    to call more than once (app.py can be run standalone or imported by
    launcher.py) - only loads once."""
    global _loaded
    if _loaded:
        return
    for path in sorted(glob.glob(os.path.join(_FONTS_DIR, "Inter-*.ttf"))):
        QFontDatabase.addApplicationFont(path)
    _loaded = True


def default_font(size=10):
    """QSS 'font-family: "Inter"' rules already cover every explicitly
    styled widget - this is the fallback for anything that isn't (native
    QMessageBox/QFileDialog text, tooltips), set once as the whole
    QApplication's default font."""
    load()
    return QFont("Inter", size)
