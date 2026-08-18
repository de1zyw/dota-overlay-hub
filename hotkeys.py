"""Global hotkeys via pynput. pynput, not `keyboard` - `keyboard` needs
root on Linux (evdev access)."""
import traceback

from pynput import keyboard

import config
import event_log


class HotkeyListener:
    def __init__(self, on_toggle, on_expand, on_self_stats, on_calibrate, on_profile_lookup, on_last_match):
        self._listener = None
        bindings = {
            config.HOTKEY_TOGGLE: on_toggle,
            config.HOTKEY_EXPAND: on_expand,
            config.HOTKEY_SELF_STATS: on_self_stats,
            config.HOTKEY_CALIBRATE: on_calibrate,
            config.HOTKEY_PROFILE_LOOKUP: on_profile_lookup,
            config.HOTKEY_LAST_MATCH: on_last_match,
        }
        # Validate each binding individually first - GlobalHotKeys parses
        # its whole dict as one unit, so a single malformed string (e.g. a
        # hand-typo'd "ctrl+alt+d" missing the "<>" via the hub's settings
        # page) would otherwise take down all six hotkeys for the session
        # with only a log line as evidence. Drop just the bad one instead.
        good_bindings = {}
        for combo, handler in bindings.items():
            try:
                keyboard.HotKey.parse(combo)
            except Exception as e:
                event_log.log(
                    "ERROR", where="hotkeys_init", exc_type=type(e).__name__,
                    message=f"invalid binding {combo!r}: {e}",
                )
            else:
                good_bindings[combo] = handler

        if not good_bindings:
            return
        try:
            self._listener = keyboard.GlobalHotKeys(good_bindings)
        except Exception as e:
            # Still guard the constructor itself - matches this codebase's
            # "auxiliary failure is silent, core feature keeps working"
            # convention (assets.py, opendota_client.py).
            event_log.log(
                "ERROR", where="hotkeys_init", exc_type=type(e).__name__,
                message=str(e), traceback=traceback.format_exc(),
            )
            self._listener = None

    def start(self):
        if self._listener:
            self._listener.start()

    def stop(self):
        if self._listener:
            self._listener.stop()
