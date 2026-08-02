# Self-stats overlay + hotkey settings — design

## Purpose

Two tightly-coupled features requested together: (1) a hotkey-triggered
overlay showing the user's own OpenDota stats in more detail than a draft
row, available at any time regardless of match state (revives "sub-project
2" from the original brainstorm — a self-stats view "by hotkey, remember?");
(2) a settings page in the hub to configure all three hotkeys (existing
toggle/expand plus the new self-stats one) instead of hardcoding them in
`config.py`. They're bundled into one spec because the new hotkey needs
somewhere to be configured, and the settings page needs a third hotkey to
exist to be worth building.

## Feature A: Self-stats overlay

- **Trigger:** a new global hotkey (default `<ctrl>+<alt>+s`), wired into
  the existing `HotkeyListener`/`_MainThreadBridge` pattern in `app.py` —
  same pynput mechanism already used for toggle/expand, same known Wayland
  limitation (works on X11, not native Wayland — already documented,
  not something this feature changes).
- **Availability:** works at any time `app.py` is running, independent of
  whether a match/draft is currently tracked — no gating on `match_state`.
  Pressing it fetches/shows regardless of what's happening in-game.
- **Data:** `fetch_player_stats(config.MY_ACCOUNT_ID)` — the same function
  already used for every teammate/enemy row. If `MY_ACCOUNT_ID is None`
  (Steam account not detected), show a plain message instead of stats:
  "Steam-аккаунт не определён — статa недоступна" rather than crashing or
  showing empty data.
- **Content (more detail than a draft row):**
  - Nickname + rank icon, at a larger size than the compact draft row.
  - Winrate and total games shown "bigger" — larger font, more prominent
    than the small inline `WR 62%` text used in the draft row.
  - **10 recent matches**, not 5 — laid out as two rows of 5
    hero-icon-plus-colored-border entries (same win=green/loss=red
    convention as the draft row), since 10 in one row would overflow.
    This requires `opendota_client.fetch_player_stats` to keep 10 matches
    instead of slicing to 5 (`recent[:10]` instead of `recent[:5]`) — the
    draft row's own rendering already slices further down to its own
    `MATCH_HISTORY_COUNT = 5` when building `_match_history_group`, so
    existing draft rows are unaffected by fetching more.
  - Top heroes: unchanged, same 3-icon strip already shown in the draft
    row (no numbers added — that option was explicitly not chosen).
- **Window:** a new `SelfStatsWindow` (separate from `OverlayWindow`, since
  content and layout differ) reusing `overlay_window._GradientPanel` and
  `assets.py`'s icon fetchers for visual consistency. Behavior: pressing
  the hotkey toggles it open/closed (no auto-hide timer — this is an
  on-demand lookup the user closes themselves by pressing the hotkey
  again, unlike the draft overlay's timed auto-hide).

## Feature B: Hotkey settings page in the hub

- New third sidebar section in `launcher.py`, **"НАСТРОЙКИ"**, alongside
  ОВЕРЛЕИ/ЛОГИ.
- Three labeled text fields, one per hotkey (Показать/скрыть,
  Свернуть/развернуть, Моя стата), pre-filled with the current values,
  same `<ctrl>+<alt>+d`-style text format pynput already uses — no key-
  capture UI, just editable text.
- One **"Сохранить"** button writes all three values to a new
  `hotkey_settings.json` in the project root.
- **New module `hotkey_settings.py`**: `load() -> dict` (three keys:
  `toggle`, `expand`, `self_stats`; returns built-in defaults —
  `<ctrl>+<alt>+d`, `<ctrl>+<alt>+e`, `<ctrl>+<alt>+s` — merged under
  whatever `hotkey_settings.json` overrides, or pure defaults if the file
  doesn't exist or fails to parse) and `save(dict)` (writes the file,
  never raises — a failed write just means the change didn't persist,
  reported by the Save button's own success/failure feedback, not a
  crash). `config.py`'s `HOTKEY_TOGGLE`/`HOTKEY_EXPAND`/new
  `HOTKEY_SELF_STATS` constants are populated by calling
  `hotkey_settings.load()` at import time, replacing the current
  hardcoded string literals.
- **Takes effect on next launch**, not live — simplest option, matches
  how pynput's `GlobalHotKeys` already binds once at `HotkeyListener`
  construction. The settings page's save confirmation says as much
  ("Сохранено — изменения применятся при следующем запуске оверлея").
- **Robustness:** `HotkeyListener`'s construction of
  `keyboard.GlobalHotKeys(...)` is wrapped in try/except — a malformed
  hotkey string (typo'd in the settings field) currently raises
  uncaught from pynput; this would crash `app.py` on every future launch
  until manually fixed. Catching it and logging an `ERROR` event (via
  `event_log`) instead, with hotkeys simply not working until corrected,
  is a lot safer for a user-editable text field than a hard crash loop.

## Testing

No automated tests, per this project's standing decision — manual
verification only: trigger the new hotkey and confirm the self-stats
window shows the expected richer content (10 matches, bigger overall
stats) both idle and during an active match; edit a hotkey in the new
settings page, confirm `hotkey_settings.json` is written correctly, and
confirm a restarted `app.py` actually binds the new value; confirm an
intentionally malformed hotkey string doesn't crash `app.py` on launch.
