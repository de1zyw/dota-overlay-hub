"""Pure pre-launch environment checks for launcher.py - no Qt dependency,
so they can be run/verified directly from a plain interpreter. Report-only:
each check just returns a severity + message, never modifies anything.

Checks are ordered machine -> network -> Dota, matching the real failure
chain: a dependency missing on THIS machine, then no route to the
internet/OpenDota specifically, then Dota's own files/config. Each layer
gets its own check so a failure points at the actual broken link instead of
one generic "stats didn't load"."""
import functools
import importlib.util
import os
import shutil
import socket
import threading
import time

import config
import error_codes

# Deliberately short and independent of opendota_client.py's own
# throttle/retry machinery (which can legitimately take up to ~30s working
# through 4 retries with backoff) - a pre-flight check should fail fast, not
# make the user wait through a retry budget meant for a live match fetch.
_NETWORK_TIMEOUT_S = 5

# check_dns/check_opendota_reachable appear in all three of the hub's own
# checklists (LAST_MATCH_CHECKS/SELF_STATS_CHECKS/PROFILE_LOOKUP_CHECKS) -
# without this, opening the hub (or hitting "Перепроверить" on more than
# one card) hits the real network 2-3x for the exact same question asked
# moments apart. Short TTL, not a real cache - "Перепроверить" clicked a
# minute later still gets a genuinely fresh answer.
_CHECK_CACHE_TTL_S = 10
_check_cache = {}
_check_cache_lock = threading.Lock()


def _cached_check(fn):
    @functools.wraps(fn)
    def wrapper():
        now = time.monotonic()
        with _check_cache_lock:
            cached = _check_cache.get(fn)
            if cached and now - cached[0] < _CHECK_CACHE_TTL_S:
                return cached[1]
        result = fn()
        with _check_cache_lock:
            _check_cache[fn] = (now, result)
        return result
    return wrapper


STATUS_OK = "ok"
STATUS_WARN = "warn"
STATUS_ERROR = "error"


def check_dependencies():
    missing = [m for m in ("PyQt6", "requests", "pynput") if importlib.util.find_spec(m) is None]
    if missing:
        return STATUS_ERROR, (
            f"Не установлены зависимости: {', '.join(missing)} "
            f"(pip install -r requirements.txt --break-system-packages) "
            f"{error_codes.tag(error_codes.MISSING_DEPENDENCY)}"
        )
    return STATUS_OK, "Все зависимости установлены"


@_cached_check
def check_dns():
    # Isolates DNS specifically from every other way a network call can
    # fail below - "DNS не резолвит" and "сервер не отвечает" point at
    # completely different fixes (router/DNS settings vs. a firewall or
    # OpenDota itself being down), so they can't share one message.
    try:
        socket.getaddrinfo("api.opendota.com", 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        return STATUS_ERROR, (
            f"DNS не резолвит api.opendota.com — похоже, нет интернета или сломан DNS "
            f"на этой машине ({e}) {error_codes.tag(error_codes.DNS_FAILURE)}"
        )
    except OSError as e:
        return STATUS_WARN, f"Не удалось проверить DNS ({e}) {error_codes.tag(error_codes.DNS_FAILURE)}"
    return STATUS_OK, "DNS резолвит OpenDota"


@_cached_check
def check_opendota_reachable():
    import requests

    try:
        resp = requests.get(
            "https://api.opendota.com/api/heroes", timeout=_NETWORK_TIMEOUT_S
        )
    except requests.exceptions.SSLError as e:
        # The classic sneaky cause here is a wrong system clock (TLS cert
        # validation fails if the machine's date is off) - worth naming
        # explicitly since "SSL error" alone sends most people looking in
        # completely the wrong place (their network, not their clock).
        return STATUS_ERROR, (
            f"TLS-ошибка при подключении к OpenDota — часто это неправильные "
            f"дата/время на машине, проверь их ({e}) {error_codes.tag(error_codes.TLS_ERROR)}"
        )
    except requests.exceptions.ConnectionError as e:
        return STATUS_ERROR, (
            f"Не удаётся подключиться к OpenDota (сеть или фаервол блокирует) — {e} "
            f"{error_codes.tag(error_codes.CONNECTION_ERROR)}"
        )
    except requests.exceptions.Timeout:
        return STATUS_WARN, (
            f"OpenDota не ответил за {_NETWORK_TIMEOUT_S}с — сервис перегружен, не наша проблема "
            f"{error_codes.tag(error_codes.TIMEOUT)}"
        )
    except requests.exceptions.RequestException as e:
        return STATUS_ERROR, f"Ошибка запроса к OpenDota — {e} {error_codes.tag(error_codes.CONNECTION_ERROR)}"

    if resp.status_code == 429:
        return STATUS_WARN, f"OpenDota сейчас лимитирует запросы — попробуй через минуту {error_codes.http_tag(429)}"
    if resp.status_code >= 500:
        return STATUS_WARN, f"OpenDota вернул ошибку сервера — не наша проблема, попробуй позже {error_codes.http_tag(resp.status_code)}"
    if resp.status_code >= 400:
        return STATUS_WARN, f"OpenDota вернул неожиданный код {error_codes.http_tag(resp.status_code)}"
    return STATUS_OK, "OpenDota API отвечает"


def check_gsi_port_free():
    # A bound-but-refused port here almost always means the overlay itself
    # is already running (it holds this port for as long as it's alive) -
    # worded as a maybe, not a definite problem, since that's the common
    # and harmless case.
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(1)
    try:
        s.bind((config.GSI_HOST, config.GSI_PORT))
    except OSError:
        return STATUS_WARN, (
            f"Порт {config.GSI_PORT} уже занят — если это не уже запущенный оверлей, "
            "live-подсветка текущего пика работать не будет, пока порт не освободится "
            f"{error_codes.tag(error_codes.GSI_PORT_BUSY)}"
        )
    finally:
        s.close()
    return STATUS_OK, f"Порт {config.GSI_PORT} для GSI свободен"


def check_portal_available():
    # Confirms the mechanism OCR screenshots depend on (portal_capture.py)
    # is even present, without actually calling Screenshot() here - that
    # would pop the real permission dialog at check-time, which belongs to
    # the moment the user actually triggers a lookup, not a background
    # health check.
    if importlib.util.find_spec("gi") is None:
        return STATUS_ERROR, (
            "python-gi не установлен — установи: sudo pacman -S python-gobject (нужен для скриншотов на Wayland) "
            f"{error_codes.tag(error_codes.PORTAL_UNAVAILABLE)}"
        )
    try:
        import gi
        gi.require_version("GLib", "2.0")
        from gi.repository import Gio, GLib

        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        variant = bus.call_sync(
            "org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
            "NameHasOwner", GLib.Variant("(s)", ("org.freedesktop.portal.Desktop",)),
            GLib.VariantType("(b)"), Gio.DBusCallFlags.NONE, 2000, None,
        )
        has_owner = variant.unpack()[0]
    except Exception as e:
        return STATUS_WARN, (
            f"Не удалось проверить XDG portal — {type(e).__name__}: {e} "
            f"{error_codes.tag(error_codes.PORTAL_UNAVAILABLE)}"
        )
    if not has_owner:
        return STATUS_ERROR, (
            "XDG Desktop Portal не запущен — скриншоты для OCR работать не будут "
            "(нужен xdg-desktop-portal + бэкенд для твоего DE, напр. xdg-desktop-portal-gnome) "
            f"{error_codes.tag(error_codes.PORTAL_UNAVAILABLE)}"
        )
    return STATUS_OK, "XDG portal доступен"


def check_dota_found():
    dota_dir = os.path.dirname(config.SERVER_LOG_PATH)
    if os.path.isdir(dota_dir):
        return STATUS_OK, "Dota 2 найдена"
    return STATUS_WARN, f"Папка Dota 2 не найдена: {dota_dir} {error_codes.tag(error_codes.DOTA_DIR_MISSING)}"


def check_gsi_cfg():
    cfg_path = os.path.join(config.GSI_CFG_DIR, "gamestate_integration_dota_overlay.cfg")
    if os.path.isfile(cfg_path):
        return STATUS_OK, "GSI-конфиг установлен"
    return STATUS_WARN, (
        f"GSI-конфиг не найден в {config.GSI_CFG_DIR} — скопируй gamestate_integration_dota_overlay.cfg туда "
        f"(live-пик работать не будет, остальная стата — будет) {error_codes.tag(error_codes.GSI_CFG_MISSING)}"
    )


def check_server_log():
    if os.path.isfile(config.SERVER_LOG_PATH):
        return STATUS_OK, "server_log.txt найден"
    return STATUS_WARN, (
        f"server_log.txt ещё не создан — появится после первого принятого матча "
        f"{error_codes.tag(error_codes.SERVER_LOG_MISSING)}"
    )


def check_steam_account():
    if config.MY_ACCOUNT_ID is not None:
        return STATUS_OK, f"Steam-аккаунт определён (account_id={config.MY_ACCOUNT_ID})"
    return STATUS_WARN, (
        f"Steam-аккаунт не определён — подсветка «это ты» работать не будет "
        f"{error_codes.tag(error_codes.STEAM_ACCOUNT_UNKNOWN)}"
    )


def check_steam_account_self_stats():
    if config.MY_ACCOUNT_ID is not None:
        return STATUS_OK, f"Steam-аккаунт определён (account_id={config.MY_ACCOUNT_ID})"
    return STATUS_WARN, (
        f"Steam-аккаунт не определён — личная стата недоступна {error_codes.tag(error_codes.STEAM_ACCOUNT_UNKNOWN)}"
    )


def check_tesseract():
    if not shutil.which("tesseract"):
        return STATUS_ERROR, (
            "tesseract не найден — установи: sudo pacman -S tesseract tesseract-data-rus tesseract-data-eng (Arch/CachyOS) "
            f"{error_codes.tag(error_codes.TESSERACT_MISSING)}"
        )
    # ocr_capture.py always reads with lang="rus+eng" - tesseract silently
    # drops any language it doesn't have data for instead of erroring, so a
    # missing pack isn't a crash, it's every nickname in that alphabet
    # coming back as garbled cross-alphabet nonsense (confirmed live: a
    # real "HelloPlayer123" OCR'd as "нецоРмует 23" with rus-only data) -
    # a plain "tesseract installed" check would miss this entirely.
    try:
        import subprocess
        result = subprocess.run(
            ["tesseract", "--list-langs"], capture_output=True, text=True, timeout=5,
        )
        installed = set(result.stdout.strip().splitlines()[1:])
    except (OSError, subprocess.SubprocessError):
        return STATUS_WARN, (
            f"tesseract найден, но не удалось проверить установленные языки "
            f"{error_codes.tag(error_codes.TESSERACT_LANG_MISSING)}"
        )
    missing = {"rus", "eng"} - installed
    if missing:
        return STATUS_WARN, (
            f"tesseract установлен, но не хватает языковых пакетов: {', '.join(sorted(missing))} "
            f"— установи: sudo pacman -S {' '.join(f'tesseract-data-{m}' for m in sorted(missing))} "
            f"(иначе OCR будет читать эти буквы как другой алфавит, без явной ошибки) "
            f"{error_codes.tag(error_codes.TESSERACT_LANG_MISSING)}"
        )
    return STATUS_OK, "tesseract установлен (rus+eng)"


def check_region_calibrated():
    import profile_lookup_settings
    if profile_lookup_settings.load() is not None:
        return STATUS_OK, "Область экрана откалибрована"
    return STATUS_WARN, (
        f"Область экрана не откалибрована — открой профиль в Доте и нажми {config.HOTKEY_CALIBRATE} "
        f"{error_codes.tag(error_codes.REGION_NOT_CALIBRATED)}"
    )


CHECKS = [
    ("Python-зависимости", check_dependencies),
    ("DNS", check_dns),
    ("OpenDota API", check_opendota_reachable),
    ("Steam/Dota 2 на диске", check_dota_found),
    ("GSI-конфиг", check_gsi_cfg),
    ("GSI-порт", check_gsi_port_free),
    ("server_log.txt", check_server_log),
    ("Steam-аккаунт", check_steam_account),
]

# Last-match recap doesn't touch server_log.txt/GSI at all (it reads
# last_match.dat locally, then polls OpenDota by match_id - see
# last_match_watcher.py) - same shorter shape as SELF_STATS_CHECKS below.
LAST_MATCH_CHECKS = [
    ("Python-зависимости", check_dependencies),
    ("DNS", check_dns),
    ("OpenDota API", check_opendota_reachable),
    ("Steam-аккаунт", check_steam_account_self_stats),
]

# Self-stats only needs the app to run and the local account to be known -
# it doesn't touch server_log.txt/GSI at all, so it gets its own shorter
# checklist rather than reusing CHECKS wholesale. It DOES need OpenDota
# though (that's the entire point of the feature), so the network layer
# stays here.
SELF_STATS_CHECKS = [
    ("Python-зависимости", check_dependencies),
    ("DNS", check_dns),
    ("OpenDota API", check_opendota_reachable),
    ("Steam-аккаунт", check_steam_account_self_stats),
]

PROFILE_LOOKUP_CHECKS = [
    ("Python-зависимости", check_dependencies),
    ("XDG portal (скриншоты)", check_portal_available),
    ("tesseract", check_tesseract),
    ("Область экрана", check_region_calibrated),
    ("DNS", check_dns),
    ("OpenDota API", check_opendota_reachable),
]
