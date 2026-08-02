"""Pure pre-launch environment checks for launcher.py - no Qt dependency,
so they can be run/verified directly from a plain interpreter. Report-only:
each check just returns a severity + message, never modifies anything."""
import importlib.util
import os

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


CHECKS = [
    ("Python-зависимости", check_dependencies),
    ("Steam/Dota 2 на диске", check_dota_found),
    ("GSI-конфиг", check_gsi_cfg),
    ("server_log.txt", check_server_log),
    ("Steam-аккаунт", check_steam_account),
]
