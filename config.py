import os

STEAM_LIBRARY = os.path.expanduser("~/.local/share/Steam")
SERVER_LOG_PATH = os.path.join(
    STEAM_LIBRARY, "steamapps/common/dota 2 beta/game/dota/server_log.txt"
)
GSI_CFG_DIR = os.path.join(
    STEAM_LIBRARY, "steamapps/common/dota 2 beta/game/dota/cfg/gamestate_integration"
)

GSI_HOST = "127.0.0.1"
GSI_PORT = 3500

AUTO_HIDE_SECONDS = 25
POLL_INTERVAL_SECONDS = 1.0
GSI_POLL_INTERVAL_SECONDS = 2.0

HOTKEY_TOGGLE = "<ctrl>+<alt>+d"
HOTKEY_EXPAND = "<ctrl>+<alt>+e"

WINRATE_GREEN = 55.0
WINRATE_RED = 45.0

COLOR_GREEN = "#3ecf5e"
COLOR_NEUTRAL = "#cccccc"
COLOR_RED = "#e2574c"

WINDOW_MARGIN_PX = 20
WINDOW_OPACITY = 0.85
