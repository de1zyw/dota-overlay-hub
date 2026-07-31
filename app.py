"""Wires lobby_watcher -> opendota_client (threaded) -> overlay_window,
with GSI-based best-effort current-pick resolution and auto-hide.

Cross-thread note: `watch_for_new_match`'s callback runs on a background
thread, and `pynput`'s `GlobalHotKeys` callbacks run on pynput's own listener
thread. Qt requires QWidget/QTimer objects to only be touched from the
thread that owns them (the Qt main/GUI thread) - touching them from another
thread is undefined behavior that Qt silently rejects with a `qWarning`
(no Python exception raised), as confirmed via `QObject::setParent` /
`QObject::startTimer` cross-thread warnings during Task 9 verification.
`_MainThreadBridge` below is a `QObject` whose signals are emitted from the
background/pynput threads but whose slots (bound methods of this QObject)
are automatically queued by Qt onto the thread that owns the bridge (the
main thread, since it is constructed inside `OverlayApp.__init__`, which
runs on the main thread) - this queuing is what performs the actual
hand-off. It specifically relies on the slots being bound methods of a
QObject with known thread affinity: PyQt's auto-connection only detects and
queues across threads when the receiver is such a QObject, which is why the
window-touching code lives in this class's own slot methods rather than in
a plain function or a bound method of the (non-QObject) `OverlayApp`.
"""
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from PyQt6.QtWidgets import QApplication

import config
from draft_matcher import match_current_picks
from gsi_server import GSIServer
from hotkeys import HotkeyListener
from lobby_watcher import watch_for_new_match
from opendota_client import fetch_player_stats
from overlay_window import OverlayWindow


class _MainThreadBridge(QObject):
    """Owns the signals that hand work off from background threads (the
    lobby watcher thread, pynput's hotkey thread) onto the Qt main thread.
    Its slots are bound methods of this QObject, so Qt's auto-connection
    queues them onto the thread that owns this bridge (the main thread)
    whenever `emit()` is called from a different thread."""

    new_match_ready = pyqtSignal(object, object, object)
    toggle_visibility_requested = pyqtSignal()
    expand_requested = pyqtSignal()

    def __init__(self, window, hide_timer):
        super().__init__()
        self._window = window
        self._hide_timer = hide_timer
        self.new_match_ready.connect(self._on_new_match_ready)
        self.toggle_visibility_requested.connect(self._on_toggle_visibility)
        self.expand_requested.connect(self._on_expand)

    def _on_new_match_ready(self, radiant, dire, current_picks):
        self._window.render_lobby(radiant, dire, current_picks)
        self._window.show_overlay()
        self._hide_timer.start(config.AUTO_HIDE_SECONDS * 1000)

    def _on_toggle_visibility(self):
        if self._window.isVisible():
            self._window.hide_overlay()
        else:
            self._window.show_overlay()

    def _on_expand(self):
        self._window.toggle_expanded()


class OverlayApp:
    def __init__(self):
        self.qt_app = QApplication(sys.argv)
        self.window = OverlayWindow()
        self.gsi = GSIServer(config.GSI_HOST, config.GSI_PORT)
        self.executor = ThreadPoolExecutor(max_workers=10)
        self.hide_timer = QTimer()
        self.hide_timer.setSingleShot(True)
        self.hide_timer.timeout.connect(self.window.hide_overlay)

        self.bridge = _MainThreadBridge(self.window, self.hide_timer)

        self.hotkeys = HotkeyListener(
            on_toggle=self.bridge.toggle_visibility_requested.emit,
            on_expand=self.bridge.expand_requested.emit,
        )

        # Last-known lobby state, set by on_new_match (background thread) and
        # read by _poll_picks (main thread). Plain attribute swaps are safe
        # here under the GIL - no lock needed since each field is replaced
        # wholesale (never mutated in place) and readers only ever see a
        # fully-formed previous or current value, never a half-written one.
        self.roster = None
        self.radiant = []
        self.dire = []

        self.pick_timer = QTimer()
        self.pick_timer.timeout.connect(self._poll_picks)

    def _poll_picks(self):
        # Runs on the main thread (QTimer's own timeout is always delivered
        # on the thread that started it) - safe to touch self.window directly,
        # no bridge hand-off needed here, unlike on_new_match/hotkey callbacks.
        if self.roster is None:
            return
        current_picks = match_current_picks(self.roster, self.gsi.latest_raw)
        self.window.render_lobby(self.radiant, self.dire, current_picks)

    def on_new_match(self, roster):
        account_ids = [account_id for _, _, account_id in roster]
        stats_by_id = dict(zip(account_ids, self.executor.map(fetch_player_stats, account_ids)))

        radiant = [stats_by_id[aid] for team, _, aid in roster if team == "radiant"]
        dire = [stats_by_id[aid] for team, _, aid in roster if team == "dire"]
        current_picks = match_current_picks(roster, self.gsi.latest_raw)

        self.roster = roster
        self.radiant = radiant
        self.dire = dire

        # This method runs on the background watcher thread - do not touch
        # self.window/self.hide_timer directly here. Hand off to the main
        # thread via the bridge signal instead.
        self.bridge.new_match_ready.emit(radiant, dire, current_picks)

    def run(self):
        self.gsi.start()
        self.hotkeys.start()
        self.pick_timer.start(int(config.GSI_POLL_INTERVAL_SECONDS * 1000))

        watcher_thread = threading.Thread(
            target=watch_for_new_match,
            args=(config.SERVER_LOG_PATH, self.on_new_match, config.POLL_INTERVAL_SECONDS),
            daemon=True,
        )
        watcher_thread.start()

        sys.exit(self.qt_app.exec())


if __name__ == "__main__":
    OverlayApp().run()
