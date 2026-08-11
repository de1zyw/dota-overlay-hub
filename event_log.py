"""Per-run JSON-Lines diagnostic log. Purely a dev-time debugging aid: the
user hands the resulting logs/run_*.jsonl file to Claude after a real match
so it can be read directly instead of the user describing what happened.
Never raises - a logging failure must never interrupt the feature it's
observing (same convention as assets.py/opendota_client.py)."""
import json
import os
import sys
import threading
import traceback
from datetime import datetime, timezone

import platform_utils

_lock = threading.Lock()
_file = None


def init(log_dir=None):
    global _file
    if log_dir is None:
        # An explicit, CWD-independent default - a relative "logs" only
        # ever worked because `python3 launcher.py` happens to be run
        # from this project's own directory; a frozen .exe can be
        # launched with a different working directory (a shortcut with
        # its own "Start in", `cmd /c cd elsewhere && app.exe`, ...).
        log_dir = os.path.join(platform_utils.data_dir(), "logs")
    with _lock:
        if _file is not None:
            return
        try:
            os.makedirs(log_dir, exist_ok=True)
            # Millisecond precision, not just seconds - two runs started
            # within the same second (e.g. a quick restart) would otherwise
            # collide onto the same filename and silently merge into one log.
            ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")[:-3]
            path = os.path.join(log_dir, f"run_{ts}.jsonl")
            _file = open(path, "a", encoding="utf-8")
        except OSError:
            _file = None


def log(event, **fields):
    with _lock:
        if _file is None:
            return
        try:
            line = {
                "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                "event": event,
                **fields,
            }
            _file.write(json.dumps(line, default=str) + "\n")
            _file.flush()
        except (OSError, TypeError, ValueError):
            pass


def _log_exception(where, exc_type, exc_value, exc_tb, thread_name):
    log(
        "ERROR",
        where=where,
        exc_type=exc_type.__name__ if exc_type else None,
        message=str(exc_value),
        traceback="".join(traceback.format_exception(exc_type, exc_value, exc_tb)),
        thread_name=thread_name,
    )


def install_exception_hooks():
    previous_excepthook = sys.excepthook
    previous_threading_excepthook = threading.excepthook

    def _excepthook(exc_type, exc_value, exc_tb):
        _log_exception("excepthook", exc_type, exc_value, exc_tb, threading.current_thread().name)
        previous_excepthook(exc_type, exc_value, exc_tb)

    def _threading_excepthook(args):
        _log_exception(
            "threading_excepthook", args.exc_type, args.exc_value, args.exc_traceback,
            args.thread.name if args.thread else "unknown",
        )
        previous_threading_excepthook(args)

    sys.excepthook = _excepthook
    threading.excepthook = _threading_excepthook
