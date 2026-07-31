"""Wires lobby_watcher -> opendota_client (threaded) -> overlay_window,
with GSI-based best-effort current-pick resolution and auto-hide."""
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication

import config
from draft_matcher import match_current_picks
from gsi_server import GSIServer
from hotkeys import HotkeyListener
from lobby_watcher import watch_for_new_match
from meta_client import fetch_top_banned_heroes
from opendota_client import fetch_player_stats
from overlay_window import OverlayWindow


class OverlayApp:
    def __init__(self):
        self.qt_app = QApplication(sys.argv)
        self.window = OverlayWindow()
        self.gsi = GSIServer(config.GSI_HOST, config.GSI_PORT)
        self.executor = ThreadPoolExecutor(max_workers=10)
        self.hide_timer = QTimer()
        self.hide_timer.setSingleShot(True)
        self.hide_timer.timeout.connect(self.window.hide_overlay)

        self.hotkeys = HotkeyListener(
            on_toggle=self._toggle_visibility,
            on_expand=self._expand,
        )

    def _toggle_visibility(self):
        if self.window.isVisible():
            self.window.hide_overlay()
        else:
            self.window.show_overlay()

    def _expand(self):
        self.window.toggle_expanded()

    def on_new_match(self, roster):
        account_ids = [account_id for _, _, account_id in roster]
        stats_by_id = dict(zip(account_ids, self.executor.map(fetch_player_stats, account_ids)))

        radiant = [stats_by_id[aid] for team, _, aid in roster if team == "radiant"]
        dire = [stats_by_id[aid] for team, _, aid in roster if team == "dire"]
        current_picks = match_current_picks(roster, self.gsi.latest_raw)
        banned_heroes = fetch_top_banned_heroes(10)

        self.window.render_lobby(radiant, dire, current_picks, banned_heroes)
        self.window.show_overlay()
        self.hide_timer.start(config.AUTO_HIDE_SECONDS * 1000)

    def run(self):
        self.gsi.start()
        self.hotkeys.start()

        watcher_thread = threading.Thread(
            target=watch_for_new_match,
            args=(config.SERVER_LOG_PATH, self.on_new_match, config.POLL_INTERVAL_SECONDS),
            daemon=True,
        )
        watcher_thread.start()

        sys.exit(self.qt_app.exec())


if __name__ == "__main__":
    OverlayApp().run()
