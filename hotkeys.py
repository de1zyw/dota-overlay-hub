"""Global show/hide and expand/collapse hotkeys via pynput.
pynput, not `keyboard` - `keyboard` needs root on Linux (evdev access)."""
from pynput import keyboard

import config


class HotkeyListener:
    def __init__(self, on_toggle, on_expand):
        self._listener = keyboard.GlobalHotKeys({
            config.HOTKEY_TOGGLE: on_toggle,
            config.HOTKEY_EXPAND: on_expand,
        })

    def start(self):
        self._listener.start()

    def stop(self):
        self._listener.stop()
