"""Pure parsing of logs/run_*.jsonl files into per-run summaries for the
hub's Logs page - no Qt dependency. Never raises: a missing logs/ dir
returns [], a malformed/partial line (e.g. from a run killed mid-write)
is skipped rather than crashing the whole listing."""
import glob
import json
import os

import platform_utils


def _summarize(path):
    event_counts = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)["event"]
            except (json.JSONDecodeError, KeyError):
                continue
            event_counts[event] = event_counts.get(event, 0) + 1

    stat = os.stat(path)
    return {
        "path": path,
        "filename": os.path.basename(path),
        "mtime": stat.st_mtime,
        "size_bytes": stat.st_size,
        "event_counts": event_counts,
        "has_error": event_counts.get("ERROR", 0) > 0,
    }


def list_log_runs(log_dir=None):
    if log_dir is None:
        log_dir = os.path.join(platform_utils.data_dir(), "logs")  # same default as event_log.init()
    if not os.path.isdir(log_dir):
        return []
    runs = [_summarize(p) for p in glob.glob(os.path.join(log_dir, "run_*.jsonl"))]
    runs.sort(key=lambda r: r["mtime"], reverse=True)
    return runs
