# Dota 2 Draft Stats Overlay

Оверлей поверх Dota 2, показывающий статистику союзников/врагов на стадии драфта: ранг,
винрейт, последние 5 матчей (иконка героя + цветная рамка W/L), текущий пик (или "?", если
ещё не пикнул) — обновляется прямо по ходу драфта.

Сделан как легальная альтернатива инструментам вроде "Overplus": никакого перехвата пакетов
и чтения памяти игры — только официальные/публичные источники данных.

## Источники данных

- **`server_log.txt`** — Dota сама пишет туда Match ID и Steam ID всех 10 игроков при принятии
  матча (`<Steam library>/steamapps/common/dota 2 beta/game/dota/server_log.txt`).
- **[OpenDota API](https://docs.opendota.com/)** — публичный, без ключа: профиль, винрейт,
  последние матчи, топ-герои.
- **Dota 2 Game State Integration (GSI)** — официальный механизм (как в CS:GO) для
  best-effort определения текущего пика героя в реальном времени.

## Установка

```bash
cd dota_overlay
pip install -r requirements.txt --break-system-packages
```

## Запуск

**Без реальной Доты** (демо на синтетическом логе + один реальный аккаунт):
```bash
QT_QPA_PLATFORM=xcb python3 run_demo.py
```
(`QT_QPA_PLATFORM=xcb` нужен на Wayland-сессиях — оверлей рисуется через XWayland.)

**С реальной Дотой:**
1. Скопировать `gamestate_integration_dota_overlay.cfg` в
   `<Steam library>/steamapps/common/dota 2 beta/game/dota/cfg/gamestate_integration/`.
2. Запустить `python3 app.py` до захода в лобби.
3. Показ/скрытие — глобальный хоткей (`config.py`, `HOTKEY_TOGGLE`/`HOTKEY_EXPAND`).
   На Wayland глобальные хоткеи не работают (ограничение компоситора, не баг) — актуально
   для X11-сессий.

## Структура

| Файл | Назначение |
|---|---|
| `config.py` | пути, хоткеи, цвета, тайминги |
| `opendota_client.py` | статистика игрока (тротлинг/кэш/ретраи) |
| `lobby_watcher.py` | парсинг/слежка за `server_log.txt` |
| `gsi_server.py` | локальный HTTP-приёмник GSI-пакетов от Dota |
| `draft_matcher.py` | best-effort сопоставление слот→герой (GSI) с слот→Steam ID (лог) |
| `assets.py` | скачивание/кэш иконок героев/рангов/фракций |
| `overlay_window.py` | само окно (PyQt, тёмная тема, иконки) |
| `hotkeys.py` | глобальные хоткеи (`pynput`) |
| `app.py` | связывает всё вместе |

## Известные ограничения

- **Wayland**: прозрачность/стили могут отличаться от X11, глобальные хоткеи не работают —
  осознанно не решается в этом заходе (по плану — X11).
- **GSI-схема для текущего пика** — best-effort гипотеза (совпадение нумерации слотов между
  `server_log.txt` и GSI draft), требует калибровки на реальном матче.
- **Приватные профили** OpenDota — показываются как "профиль скрыт", это не баг, а ограничение
  самого OpenDota (игрок сам выключил "Expose Public Match Data").

## Документация процесса

Полная спека и план реализации (с историей ревью каждой таски) — в
`docs/superpowers/specs/` и `docs/superpowers/plans/`.
