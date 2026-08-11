"""Checks whether a newer build is available on GitHub than the one
currently running. Only meaningful for a frozen (PyInstaller) build - a
dev checkout has no baked-in build_version.txt and no build.bat-driven
update path, so it's simply skipped there. Never raises: any failure
(no internet, GitHub down, rate-limited) just means "no update info",
same silent-degrade convention as the rest of this app's network calls.
"""
import os
import subprocess

import requests

import platform_utils

_REPO = "de1zyw/dota-overlay-hub"
_COMMITS_URL = f"https://api.github.com/repos/{_REPO}/commits/master"


def _read_build_sha():
    try:
        with open(platform_utils.resource_path("build_version.txt"), encoding="utf-8") as f:
            sha = f.read().strip()
    except OSError:
        return None
    return sha or None


def _fetch_latest_sha(timeout=5):
    try:
        resp = requests.get(
            _COMMITS_URL,
            headers={"User-Agent": "dota-overlay-hub-update-check"},
            timeout=timeout,
        )
        resp.raise_for_status()
        return resp.json()["sha"]
    except (requests.RequestException, ValueError, KeyError):
        return None


def check_for_update():
    """Returns True only when both SHAs are known and genuinely differ -
    anything uncertain (missing build marker, network failure) returns
    False rather than nagging the user with a false positive."""
    if not platform_utils.IS_FROZEN:
        return False
    current = _read_build_sha()
    if current is None or current == "unknown":
        return False
    latest = _fetch_latest_sha()
    if latest is None:
        return False
    return not latest.startswith(current) and not current.startswith(latest)


def relaunch_build_and_exit():
    """Re-runs build.bat (which lives next to the exe after any successful
    build - bootstrapped or not) in its own console window, then the
    caller should quit the app immediately so the exe file isn't locked
    when build.bat tries to overwrite it. Windows-only - build.bat is a
    batch file, and this whole rebuild-in-place flow doesn't exist for
    the Linux install (install.sh isn't self-rerunning like this)."""
    if not platform_utils.IS_WINDOWS:
        return False
    build_bat = os.path.join(platform_utils.data_dir(), "build.bat")
    if not os.path.isfile(build_bat):
        return False
    subprocess.Popen(["cmd", "/c", "start", "", "build.bat"], cwd=platform_utils.data_dir())
    return True
