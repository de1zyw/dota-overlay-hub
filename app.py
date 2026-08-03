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
from assets import prefetch_all_icons
from draft_matcher import match_current_picks
from gsi_server import GSIServer
from hotkeys import HotkeyListener
from lobby_watcher import watch_for_new_match
import profile_lookup_history
import profile_lookup_settings
from candidate_picker_window import CandidatePickerWindow
from ocr_capture import capture_region, read_nickname
from opendota_client import fetch_player_stats, search_players
from overlay_window import OverlayWindow
from player_stats_window import PlayerStatsWindow
from region_calibrator import RegionCalibrator


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
    calibrate_requested = pyqtSignal()
    profile_lookup_ready = pyqtSignal(object)

    def __init__(self, window, hide_timer, player_stats_window):
        super().__init__()
        self._window = window
        self._hide_timer = hide_timer
        self._player_stats_window = player_stats_window
        self._active_calibrator = None
        self._active_picker = None
        self.new_match_ready.connect(self._on_new_match_ready)
        self.toggle_visibility_requested.connect(self._on_toggle_visibility)
        self.expand_requested.connect(self._on_expand)
        self.self_stats_ready.connect(self._on_self_stats_ready)
        self.calibrate_requested.connect(self._on_calibrate_requested)
        self.profile_lookup_ready.connect(self._on_profile_lookup_ready)

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
        if self._player_stats_window.isVisible():
            self._player_stats_window.hide_stats()
        else:
            self._player_stats_window.render_stats(stats)
            self._player_stats_window.show_stats()

    def _on_calibrate_requested(self):
        event_log.log("HOTKEY", action="calibrate")
        if self._active_calibrator is not None:
            # Already calibrating - a second press here would orphan the
            # first fullscreen overlay (its Python reference gets overwritten
            # below, but the still-visible window would linger disconnected
            # from anything that could close it).
            return
        self._active_calibrator = RegionCalibrator(on_done=self._on_calibration_done)

    def _on_calibration_done(self, region):
        event_log.log("CALIBRATION_DONE", region=region)
        self._active_calibrator = None

    def _on_profile_lookup_ready(self, candidates):
        event_log.log("HOTKEY", action="profile_lookup")
        if not candidates:
            self._player_stats_window.render_stats(
                None, empty_message="Профиль не распознан или не найден на OpenDota"
            )
            self._player_stats_window.show_stats()
            return
        if len(candidates) == 1:
            self._show_profile(candidates[0]["account_id"])
        elif self._active_picker is None:
            # Same reasoning as _on_calibrate_requested above - don't orphan
            # an already-open picker window by overwriting its reference.
            self._active_picker = CandidatePickerWindow(on_selected=self._on_candidate_selected)
            self._active_picker.show_candidates(candidates)

    def _on_candidate_selected(self, candidate):
        self._active_picker = None
        self._show_profile(candidate["account_id"])

    def _show_profile(self, account_id):
        # Brief main-thread block on this one fetch - acceptable here since
        # it only runs right after an explicit user action (a hotkey press
        # that resolved to exactly one match, or a picker click), not on
        # every poll tick like _poll_picks.
        stats = fetch_player_stats(account_id)
        self._player_stats_window.render_stats(stats)
        self._player_stats_window.show_stats()
        match_ids = [match_id for _, _, match_id in stats.recent_matches if match_id is not None]
        profile_lookup_history.append(account_id, stats.nickname, match_ids)


class OverlayApp:
    def __init__(self):
        self.window = OverlayWindow()
        self.player_stats_window = PlayerStatsWindow()
        self.gsi = GSIServer(config.GSI_HOST, config.GSI_PORT)
        self.executor = ThreadPoolExecutor(max_workers=10)
        self.hide_timer = QTimer()
        self.hide_timer.setSingleShot(True)

        self.bridge = _MainThreadBridge(self.window, self.hide_timer, self.player_stats_window)
        self.hide_timer.timeout.connect(lambda: self.bridge.on_auto_hide())

        self.hotkeys = HotkeyListener(
            on_toggle=self.bridge.toggle_visibility_requested.emit,
            on_expand=self.bridge.expand_requested.emit,
            on_self_stats=self.on_self_stats_hotkey,
            on_calibrate=self.bridge.calibrate_requested.emit,
            on_profile_lookup=self.on_profile_lookup_hotkey,
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
        event_log.log("HOTKEY", action="self_stats")
        stats = fetch_player_stats(config.MY_ACCOUNT_ID) if config.MY_ACCOUNT_ID else None
        self.bridge.self_stats_ready.emit(stats)

    def on_profile_lookup_hotkey(self):
        # Runs on pynput's own listener thread - safe to block here on
        # screen capture, OCR, and the network search call. Only the
        # actual window show/hide + render must happen on the main
        # thread, via the bridge signal below.
        event_log.log("PROFILE_LOOKUP_HOTKEY")
        region = profile_lookup_settings.load()
        if region is None:
            event_log.log("PROFILE_LOOKUP_RESULT", stage="no_region")
            self.bridge.profile_lookup_ready.emit([])
            return
        image = capture_region(region)
        # Logged even on success - the raw OCR text is the single most
        # useful piece of evidence when a lookup fails downstream (bad
        # crop, wrong font contrast, wrong language pack all show up
        # here as garbled/empty text, distinct from "OCR read a real
        # nickname but OpenDota search found no match").
        nickname = read_nickname(image)
        event_log.log(
            "PROFILE_LOOKUP_RESULT", stage="ocr_done",
            captured=image is not None, nickname=nickname,
        )
        if not nickname:
            self.bridge.profile_lookup_ready.emit([])
            return
        candidates = search_players(nickname)
        event_log.log(
            "PROFILE_LOOKUP_RESULT", stage="search_done",
            candidate_count=len(candidates),
        )
        self.bridge.profile_lookup_ready.emit(candidates)

    def start_services(self):
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

        # Warms the icon cache well before matchmaking could possibly find a
        # game - see prefetch_all_icons()'s own docstring for why a cold
        # cache during a real draft would freeze the UI.
        threading.Thread(target=prefetch_all_icons, daemon=True).start()

    def run(self):
        self.start_services()
        sys.exit(QApplication.instance().exec())


if __name__ == "__main__":
    qt_app = QApplication(sys.argv)
    qt_app.setWindowIcon(QIcon(os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.png")))
    OverlayApp().run()
