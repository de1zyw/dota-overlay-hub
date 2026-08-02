# Overlay Hub — design (supersedes the plain launcher's UI)

## Purpose

Grow `launcher.py` from a single pre-launch checklist into a proper small
hub application: one place that (1) lists launchable overlays with their
readiness checklist, and (2) lets the user browse past diagnostic run logs
without touching a terminal. Same dark-gradient visual identity as the
overlay itself, just a bigger window with real navigation instead of one
flat list. Check logic (`launcher_checks.py`) and launch behavior
(subprocess + close) from the already-approved launcher design are
unchanged — this is purely a UI/structure expansion plus a new Logs
section.

## Structure

Two sections, switched via a left sidebar (two buttons: "ОВЕРЛЕИ" /
"ЛОГИ") driving a `QStackedWidget`:

### 1. Overlays page

A list of "overlay cards" — today exactly one (Драфт-статы), but the list
is data-driven (`OVERLAY_ENTRIES`, each `{name, description, checks,
entry_script}`) so a second overlay drops in as one more entry later, no
structural change needed. Each card: name + one-line description, the
existing checklist rows (from `launcher_checks.CHECKS`), a small inline
status pill ("готово" green / "есть предупреждения" amber / "не готово"
red, driven by the same OK/WARN/ERROR severities), and its own "Запустить"
button (disabled iff that card's checks include an ERROR). Behavior
identical to the already-built Task 2 checklist — just wrapped in a
card instead of being the whole window.

### 2. Logs page (new)

- Left: a list of every `logs/run_*.jsonl` file, newest first, each row
  showing the run's timestamp (parsed from the filename) and file size.
  A small red dot marks any run whose log contains at least one `ERROR`
  event, so a crashed run is visible at a glance without opening it.
- Right: selecting a row shows an event-count breakdown for that run (e.g.
  `MATCH_FOUND: 1`, `STATS_FETCH: 10`, `PICK_POLL: 214`, `ERROR: 1`) —
  enough to judge at a glance whether a run looks healthy before deciding
  whether to hand it to Claude, without needing to open the raw JSONL.
- Two actions: **"Открыть папку с логами"** (opens `logs/` in the desktop
  file manager via `xdg-open`, so the user can find-and-send the file
  easily) and **"Скопировать путь"** (copies the selected file's absolute
  path to the clipboard).
- If `logs/` doesn't exist yet (no run has happened this install), show a
  single centered message instead of an empty list: "Логов пока нет —
  запусти оверлей хотя бы раз."

## New module: `logs_view.py`

Pure logic, no Qt (same separation as `launcher_checks.py`):
- `list_log_runs(log_dir="logs") -> list[dict]`, each dict:
  `{path, filename, mtime, size_bytes, event_counts: dict[str, int],
  has_error: bool}`. Parses each file's events by streaming line-by-line
  (tolerant of a trailing partial/corrupt line from a run that was killed
  mid-write — skip lines that fail `json.loads` rather than raising).
  Sorted newest-first by `mtime`.

## Window

Resizable (not fixed-width like the plain checklist draft), reasonable
default size (e.g. 760×560) so both the card list and the log preview
panel have room to breathe — "больше и красивее" per explicit request.
Sidebar and content area both sit inside (or beside) the existing
`_GradientPanel` background treatment for visual continuity with the rest
of the app.

## Testing

No automated tests, per this project's standing decision — manual
verification only: run `launcher.py`, confirm both sidebar sections
render, confirm the Overlays card's checklist/launch behavior is unchanged
from the already-verified plain launcher, and confirm the Logs page lists
the runs already produced during the diagnostic-log feature's own manual
testing earlier this session, with correct event counts and no crash on
an empty/missing `logs/` directory.
