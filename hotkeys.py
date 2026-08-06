"""Global hotkeys via pynput. pynput, not `keyboard` - `keyboard` needs
root on Linux (evdev access)."""
import traceback

from pynput import keyboard

import config
import event_log


class HotkeyListener:
    def __init__(self, on_toggle, on_expand, on_self_stats, on_calibrate, on_profile_lookup, on_last_match):
        self._listener = None
        try:
            self._listener = keyboard.GlobalHotKeys({
                config.HOTKEY_TOGGLE: on_toggle,
                config.HOTKEY_EXPAND: on_expand,
                config.HOTKEY_SELF_STATS: on_self_stats,
                config.HOTKEY_CALIBRATE: on_calibrate,
                config.HOTKEY_PROFILE_LOOKUP: on_profile_lookup,
                config.HOTKEY_LAST_MATCH: on_last_match,
            })
        except Exception as e:
            # A malformed hotkey string (e.g. hand-typo'd via the hub's
            # settings page) would otherwise crash app.py on every future
            # launch until manually fixed - log it and run with no hotkeys
            # bound instead of crashing, matching this codebase's
            # "auxiliary failure is silent, core feature keeps working"
            # convention (assets.py, opendota_client.py).
            event_log.log(
                "ERROR", where="hotkeys_init", exc_type=type(e).__name__,
                message=str(e), traceback=traceback.format_exc(),
            )

    def start(self):
        if self._listener:
            self._listener.start()

    def stop(self):
        if self._listener:
            self._listener.stop()
