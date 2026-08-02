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
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication

import config
import event_log
from draft_matcher import match_current_picks
from gsi_server import GSIServer
from hotkeys import HotkeyListener
from lobby_watcher import watch_for_new_match
from opendota_client import fetch_player_stats
from overlay_window import OverlayWindow
from self_stats_window import SelfStatsWindow


@dataclass(frozen=True)
class MatchState:
    """Bundles the last-known lobby state as one immutable object, so it can
    be published with a single atomic attribute assignment (see the comment
    on `OverlayApp.match_state` for why that matters). Add new fields here
    (e.g. a future `party_account_ids`) rather than as separate `OverlayApp`
    attributes, to keep the single-assignment guarantee intact."""

    roster: list
    radiant: list
    dire: list
    party_account_ids: set


class _MainThreadBridge(QObject):
    """Owns the signals that hand work off from background threads (the
    lobby watcher thread, pynput's hotkey thread) onto the Qt main thread.
    Its slots are bound methods of this QObject, so Qt's auto-connection
    queues them onto the thread that owns this bridge (the main thread)
    whenever `emit()` is called from a different thread."""

    new_match_ready = pyqtSignal(object, object, object, object)
    toggle_visibility_requested = pyqtSignal()
    expand_requested = pyqtSignal()
    self_stats_ready = pyqtSignal(object)

    def __init__(self, window, hide_timer, self_stats_window):
        super().__init__()
        self._window = window
        self._hide_timer = hide_timer
        self._self_stats_window = self_stats_window
        self.new_match_ready.connect(self._on_new_match_ready)
        self.toggle_visibility_requested.connect(self._on_toggle_visibility)
        self.expand_requested.connect(self._on_expand)
        self.self_stats_ready.connect(self._on_self_stats_ready)

    def _on_new_match_ready(self, radiant, dire, current_picks, party_account_ids):
        self._window.render_lobby(radiant, dire, current_picks, party_account_ids)
        event_log.log("OVERLAY_SHOW", reason="new_match")
        self._window.show_overlay()
        self._hide_timer.start(config.AUTO_HIDE_SECONDS * 1000)

    def _on_toggle_visibility(self):
        event_log.log("HOTKEY", action="toggle")
        if self._window.isVisible():
            event_log.log("OVERLAY_HIDE", reason="hotkey")
            self._window.hide_overlay()
        else:
            event_log.log("OVERLAY_SHOW", reason="hotkey")
            self._window.show_overlay()

    def _on_expand(self):
        event_log.log("HOTKEY", action="expand")
        self._window.toggle_expanded()

    def on_auto_hide(self):
        event_log.log("OVERLAY_HIDE", reason="auto_hide")
        self._window.hide_overlay()

    def _on_self_stats_ready(self, stats):
        # Always re-fetched on every hotkey press (see OverlayApp.
        # on_self_stats_hotkey below), including the press that's about to
        # close it - a same-account repeat fetch within 30s is served from
        # opendota_client's own cache, so this is cheap, not wasteful.
        if self._self_stats_window.isVisible():
            self._self_stats_window.hide_stats()
        else:
            self._self_stats_window.render_stats(stats)
            self._self_stats_window.show_stats()


class OverlayApp:
    def __init__(self):
        self.qt_app = QApplication(sys.argv)
        self.qt_app.setWindowIcon(QIcon(os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.png")))
        self.window = OverlayWindow()
        self.self_stats_window = SelfStatsWindow()
        self.gsi = GSIServer(config.GSI_HOST, config.GSI_PORT)
        self.executor = ThreadPoolExecutor(max_workers=10)
        self.hide_timer = QTimer()
        self.hide_timer.setSingleShot(True)

        self.bridge = _MainThreadBridge(self.window, self.hide_timer, self.self_stats_window)
        self.hide_timer.timeout.connect(lambda: self.bridge.on_auto_hide())

        self.hotkeys = HotkeyListener(
            on_toggle=self.bridge.toggle_visibility_requested.emit,
            on_expand=self.bridge.expand_requested.emit,
            on_self_stats=self.on_self_stats_hotkey,
        )

        # Last-known lobby state, set by on_new_match (background thread) and
        # read by _poll_picks (main thread). Bundled into a single MatchState
        # object and published via one attribute assignment - that single
        # reference assignment is atomic under the GIL, so a reader always
        # sees either the previous fully-formed MatchState or the new one,
        # never a mix of old/new fields. Three separate attribute
        # assignments (roster, then radiant, then dire) would NOT be safe:
        # the GIL can switch threads between any two bytecode instructions
        # (not just between logical statements), so _poll_picks could
        # observe e.g. a new roster paired with a stale radiant/dire from
        # the previous match for one tick.
        self.match_state = None

        self.pick_timer = QTimer()
        self.pick_timer.timeout.connect(self._poll_picks)

    def _poll_picks(self):
        # Runs on the main thread (QTimer's own timeout is always delivered
        # on the thread that started it) - safe to touch self.window directly,
        # no bridge hand-off needed here, unlike on_new_match/hotkey callbacks.
        state = self.match_state
        if state is None:
            return
        current_picks = match_current_picks(state.roster, self.gsi.latest_raw)
        event_log.log("PICK_POLL", picks=current_picks)
        self.window.render_lobby(state.radiant, state.dire, current_picks, state.party_account_ids)

    def on_new_match(self, roster, party_account_ids):
        account_ids = [account_id for _, _, account_id in roster]
        stats_by_id = dict(zip(account_ids, self.executor.map(fetch_player_stats, account_ids)))

        radiant = [stats_by_id[aid] for team, _, aid in roster if team == "radiant"]
        dire = [stats_by_id[aid] for team, _, aid in roster if team == "dire"]

        event_log.log(
            "MATCH_FOUND",
            radiant=[aid for team, _, aid in roster if team == "radiant"],
            dire=[aid for team, _, aid in roster if team == "dire"],
            party=sorted(party_account_ids),
        )
        for stats in stats_by_id.values():
            event_log.log("STATS_FETCH", account_id=stats.account_id, nickname=stats.nickname, hidden=stats.hidden)

        current_picks = match_current_picks(roster, self.gsi.latest_raw)

        self.match_state = MatchState(roster, radiant, dire, party_account_ids)

        # This method runs on the background watcher thread - do not touch
        # self.window/self.hide_timer directly here. Hand off to the main
        # thread via the bridge signal instead.
        self.bridge.new_match_ready.emit(radiant, dire, current_picks, party_account_ids)

    def on_self_stats_hotkey(self):
        # Runs on pynput's own listener thread (see this module's
        # docstring) - blocking here on the network fetch is fine, it
        # doesn't freeze the UI. Only the actual show/hide + render must
        # happen on the main thread, via the bridge signal below.
        stats = fetch_player_stats(config.MY_ACCOUNT_ID) if config.MY_ACCOUNT_ID else None
        self.bridge.self_stats_ready.emit(stats)

    def run(self):
        event_log.init()
        event_log.install_exception_hooks()
        event_log.log("APP_START", pid=os.getpid())

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
