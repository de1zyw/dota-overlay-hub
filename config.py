import os

from hotkey_settings import load as _load_hotkeys
from local_steam import get_local_account_id

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

_hotkeys = _load_hotkeys()
HOTKEY_TOGGLE = _hotkeys["toggle"]
HOTKEY_EXPAND = _hotkeys["expand"]
HOTKEY_SELF_STATS = _hotkeys["self_stats"]

WINRATE_GREEN = 55.0
WINRATE_RED = 45.0

COLOR_GREEN = "#3ecf5e"
COLOR_NEUTRAL = "#cccccc"
COLOR_RED = "#e2574c"

WINDOW_MARGIN_PX = 20
# Task 18: raised from 0.85 - user feedback was that the overlay was too
# see-through to read comfortably over live gameplay. 0.97 keeps a sliver of
# translucency (so it still reads as an overlay, not an opaque window
# floating over the game) while making text/icons solid enough to read at a
# glance. Combined with BASE_BG's higher alpha below (the two multiply:
# this scales the whole rendered window, BASE_BG only the panel fill).
WINDOW_OPACITY = 0.97

# The locally logged-in Steam account's account_id (Steam32), auto-detected
# from Steam's own loginusers.vdf - or None if it can't be determined (e.g.
# this dev machine, which has no real Steam login). Used by overlay_window
# to highlight "this is you" among the rows. Detection never raises, so
# import of this module is always safe even without Steam installed.
MY_ACCOUNT_ID = get_local_account_id()
