# Pre-launch checklist launcher — design

## Purpose

A small GUI utility, `launcher.py`, that runs before the overlay itself:
checks the environment the overlay depends on, reports what's wrong (no
auto-fixing), and offers a "Launch" button that starts the overlay
(`app.py`) once the user is ready. Visually matches `overlay_window.py`'s
dark-gradient theme. **Linux only for now** — a Windows launcher is
explicitly deferred until Windows Dota 2 is actually installed and
playable (currently blocked on a driver issue, tracked separately).

## Checks

Each check returns one of three severities:

- **OK** (green ✓) — nothing to report.
- **WARNING** (amber !) — degraded but launchable; the overlay still runs,
  just with reduced functionality.
- **ERROR** (red ✗, hard blocker) — the overlay would crash outright if
  launched; disables the Launch button until fixed.

| Check | Severity if failing | Why |
|---|---|---|
| Python deps (`PyQt6`, `requests`, `pynput` importable via `importlib.util.find_spec`) | ERROR | Missing any of these crashes `app.py` immediately on import. |
| Steam/Dota 2 folder found (`dirname(config.SERVER_LOG_PATH)` is a directory) | WARNING | Overlay still starts; it just never detects a match. |
| GSI config installed (`gamestate_integration_dota_overlay.cfg` present under `config.GSI_CFG_DIR`) | WARNING | Overlay still shows all stats; only live current-pick detection is degraded (matches existing "?" placeholder behavior). |
| `server_log.txt` exists (`config.SERVER_LOG_PATH`) | WARNING | Legitimately absent until the user's first-ever accepted match; purely informational. |
| Local Steam account detected (`config.MY_ACCOUNT_ID is not None`) | WARNING | Only affects the "this is you" row highlight; everything else still works. |

Report-only: the launcher never installs packages, copies files, or
modifies anything — it only tells the user what to fix (with the exact
path/command, reusing the wording already in `README.md`) and provides a
"Перепроверить" (Recheck) button to re-run all checks after they've fixed
something manually.

## UI

- A normal (non-frameless, has OS window chrome/close button) `QWidget`
  window — unlike the overlay, this is a foreground utility window the
  user actively interacts with before playing, not something meant to sit
  on top of gameplay.
- Content area reuses `overlay_window._GradientPanel` (imported directly)
  for the same dark near-black background + soft pink/blue/purple gradient
  glow as the overlay, so it visually reads as part of the same app
  ("в таком же стиле как наш драфтер").
- One row per check: status icon (✓/!/✗, colored via `config.COLOR_GREEN` /
  an amber warning color / `config.COLOR_RED`), the check's short label,
  and — only when not OK — a wrapped detail line explaining what's wrong
  and how to fix it.
- Two buttons: **"Перепроверить"** (re-runs all checks, rebuilds the rows)
  and **"Запустить"** (Launch) — disabled whenever any check reports
  ERROR, enabled otherwise (WARNINGs never block launch, per explicit
  user choice).
- Checks run once automatically on window open, so the user sees status
  immediately without an extra click.

## Launch behavior

Clicking "Запустить": spawn `app.py` as an independent subprocess
(`subprocess.Popen([sys.executable, "app.py"], cwd=<project dir>)` — a
separate OS process, not an in-process import, since `app.py` constructs
its own `QApplication` and two `QApplication` instances in one process is
unsupported), then close the launcher window and quit its own
`QApplication` — per explicit user choice, the launcher's job is done at
that point and it exits rather than staying open to show status.

## Testing

No automated tests, per this project's standing decision — manual
verification only: run `launcher.py`, confirm each check reports the
expected status in a controlled scenario (e.g. temporarily rename the GSI
cfg to see it flip to WARNING, confirm Launch stays enabled; simulate a
missing dependency by checking the button-disable logic directly), then
click Launch and confirm `app.py` starts as a separate process while the
launcher window closes.
