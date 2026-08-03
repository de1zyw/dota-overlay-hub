"""Pure pre-launch environment checks for launcher.py - no Qt dependency,
so they can be run/verified directly from a plain interpreter. Report-only:
each check just returns a severity + message, never modifies anything."""
import importlib.util
import os
import shutil

import config

STATUS_OK = "ok"
STATUS_WARN = "warn"
STATUS_ERROR = "error"


def check_dependencies():
    missing = [m for m in ("PyQt6", "requests", "pynput") if importlib.util.find_spec(m) is None]
    if missing:
        return STATUS_ERROR, f"Не установлены зависимости: {', '.join(missing)} (pip install -r requirements.txt --break-system-packages)"
    return STATUS_OK, "Все зависимости установлены"


def check_dota_found():
    dota_dir = os.path.dirname(config.SERVER_LOG_PATH)
    if os.path.isdir(dota_dir):
        return STATUS_OK, "Dota 2 найдена"
    return STATUS_WARN, f"Папка Dota 2 не найдена: {dota_dir}"


def check_gsi_cfg():
    cfg_path = os.path.join(config.GSI_CFG_DIR, "gamestate_integration_dota_overlay.cfg")
    if os.path.isfile(cfg_path):
        return STATUS_OK, "GSI-конфиг установлен"
    return STATUS_WARN, f"GSI-конфиг не найден в {config.GSI_CFG_DIR} — скопируй gamestate_integration_dota_overlay.cfg туда (live-пик работать не будет, остальная стата — будет)"


def check_server_log():
    if os.path.isfile(config.SERVER_LOG_PATH):
        return STATUS_OK, "server_log.txt найден"
    return STATUS_WARN, "server_log.txt ещё не создан — появится после первого принятого матча"


def check_steam_account():
    if config.MY_ACCOUNT_ID is not None:
        return STATUS_OK, f"Steam-аккаунт определён (account_id={config.MY_ACCOUNT_ID})"
    return STATUS_WARN, "Steam-аккаунт не определён — подсветка «это ты» работать не будет"


def check_steam_account_self_stats():
    if config.MY_ACCOUNT_ID is not None:
        return STATUS_OK, f"Steam-аккаунт определён (account_id={config.MY_ACCOUNT_ID})"
    return STATUS_WARN, "Steam-аккаунт не определён — личная стата недоступна"


def check_tesseract():
    if not shutil.which("tesseract"):
        return STATUS_ERROR, "tesseract не найден — установи: sudo pacman -S tesseract tesseract-data-rus tesseract-data-eng (Arch/CachyOS)"
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
        return STATUS_WARN, "tesseract найден, но не удалось проверить установленные языки"
    missing = {"rus", "eng"} - installed
    if missing:
        return STATUS_WARN, (
            f"tesseract установлен, но не хватает языковых пакетов: {', '.join(sorted(missing))} "
            f"— установи: sudo pacman -S {' '.join(f'tesseract-data-{m}' for m in sorted(missing))} "
            "(иначе OCR будет читать эти буквы как другой алфавит, без явной ошибки)"
        )
    return STATUS_OK, "tesseract установлен (rus+eng)"


def check_region_calibrated():
    import profile_lookup_settings
    if profile_lookup_settings.load() is not None:
        return STATUS_OK, "Область экрана откалибрована"
    return STATUS_WARN, f"Область экрана не откалибрована — открой профиль в Доте и нажми {config.HOTKEY_CALIBRATE}"


CHECKS = [
    ("Python-зависимости", check_dependencies),
    ("Steam/Dota 2 на диске", check_dota_found),
    ("GSI-конфиг", check_gsi_cfg),
    ("server_log.txt", check_server_log),
    ("Steam-аккаунт", check_steam_account),
]

# Self-stats only needs the app to run and the local account to be known -
# it doesn't touch server_log.txt/GSI at all, so it gets its own shorter
# checklist rather than reusing CHECKS wholesale.
SELF_STATS_CHECKS = [
    ("Python-зависимости", check_dependencies),
    ("Steam-аккаунт", check_steam_account_self_stats),
]

PROFILE_LOOKUP_CHECKS = [
    ("Python-зависимости", check_dependencies),
    ("tesseract", check_tesseract),
    ("Область экрана", check_region_calibrated),
]
