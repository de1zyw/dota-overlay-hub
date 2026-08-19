"""Checks whether a newer *release* is available on GitHub than the one
currently running. Only meaningful for a frozen (PyInstaller) build - a
dev checkout has no baked-in build_version.txt and no build.bat-driven
update path, so it's simply skipped there. Never raises: any failure
(no internet, GitHub down, rate-limited) just means "no update info",
same silent-degrade convention as the rest of this app's network calls.

Deliberately checks the latest tagged *release*, not raw master HEAD -
master gets committed to mid-fix constantly during active development;
comparing against that would nag the user to rebuild into a possibly
half-broken state. A release is only cut when a point is actually meant
to be handed to someone."""
import webbrowser

import requests

import platform_utils

_REPO = "de1zyw/dota-overlay-hub"
_LATEST_RELEASE_URL = f"https://api.github.com/repos/{_REPO}/releases/latest"
_RELEASES_PAGE_URL = f"https://github.com/{_REPO}/releases/latest"


def _read_build_tag():
    try:
        with open(platform_utils.resource_path("build_version.txt"), encoding="utf-8") as f:
            tag = f.read().strip()
    except OSError:
        return None
    return tag or None


def _fetch_latest_release_tag(timeout=5):
    try:
        resp = requests.get(
            _LATEST_RELEASE_URL,
            headers={"User-Agent": "dota-overlay-hub-update-check"},
            timeout=timeout,
        )
        resp.raise_for_status()
        return resp.json()["tag_name"]
    except (requests.RequestException, ValueError, KeyError):
        return None


def check_for_update():
    """Returns True only when both tags are known and genuinely differ -
    anything uncertain (missing build marker, network failure, no
    releases published yet) returns False rather than nagging the user
    with a false positive."""
    if not platform_utils.IS_FROZEN:
        return False
    current = _read_build_tag()
    if current is None or current == "unknown":
        return False
    latest = _fetch_latest_release_tag()
    if latest is None:
        return False
    return latest != current


def open_latest_release_page():
    """Distribution moved from "friend self-builds via build.bat" to a
    CI-built Inno Setup installer attached to each GitHub Release (see
    installer.iss / .github/workflows/build-installer.yml) - there's no
    exe to overwrite in-place anymore, so the update flow is just "send
    them to the download page", same on every platform. Never raises:
    webbrowser.open() failing (no default browser configured, headless
    box) just means the button didn't do anything, not a crash."""
    try:
        webbrowser.open(_RELEASES_PAGE_URL)
        return True
    except Exception:
        return False


