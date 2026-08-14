#!/bin/bash
# One-time setup: installs Python deps, creates an app-menu entry (like on
# Fedora), and copies the GSI config into Dota's auto-detected folder.
# Safe to re-run any time (e.g. after moving the project folder).
set -e

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

# Самозагрузка: если этого файла нет рядом с launcher.py (скрипт отправили
# отдельно), скачиваем весь проект. GitHub недоступен без VPN для части
# пользователей в России - пробуем его первым (у большинства он работает),
# и только при неудаче переключаемся на зеркало (self-hosted Gitea за
# Cloudflare Tunnel, отдаёт тот же самый код без VPN).
if [ ! -f "$PROJECT_DIR/launcher.py" ]; then
    echo "== Проекта рядом нет - скачиваю =="
    if curl -fsSL --max-time 8 -o /tmp/dota-overlay-hub.zip \
        https://github.com/de1zyw/dota-overlay-hub/archive/refs/heads/master.zip 2>/dev/null; then
        echo "Скачано с GitHub."
    elif curl -fsSL --max-time 15 -o /tmp/dota-overlay-hub.zip \
        https://sort-kinds-outcomes-premiere.trycloudflare.com/piuser/dota-overlay-hub/archive/master.zip 2>/dev/null; then
        echo "GitHub недоступен - скачано с зеркала (без VPN)."
    else
        echo "ОШИБКА: не удалось скачать проект ни с GitHub, ни с зеркала."
        exit 1
    fi
    unzip -q /tmp/dota-overlay-hub.zip -d /tmp/dota-overlay-hub-extracted
    EXTRACTED_DIR="$(find /tmp/dota-overlay-hub-extracted -maxdepth 1 -mindepth 1 -type d | head -1)"
    cp -r "$EXTRACTED_DIR"/. "$PROJECT_DIR/"
    rm -rf /tmp/dota-overlay-hub.zip /tmp/dota-overlay-hub-extracted
fi

echo "== Устанавливаю Python-зависимости =="
pip install -r requirements.txt --break-system-packages

echo "== Создаю ярлык в меню приложений =="
mkdir -p ~/.local/share/applications
cat > ~/.local/share/applications/dota-overlay-hub.desktop << EOF
[Desktop Entry]
Type=Application
Name=Dota Overlay Hub
Comment=Легальный оверлей статы для драфта Dota 2
Exec=python3 launcher.py
Path=$PROJECT_DIR
Icon=$PROJECT_DIR/icon.png
Terminal=false
Categories=Game;
StartupWMClass=launcher.py
EOF

if command -v update-desktop-database &> /dev/null; then
    update-desktop-database ~/.local/share/applications
fi

echo "== Ищу папку Dota 2 и GSI-конфиг =="
GSI_DIR="$(python3 -c 'import config; print(config.GSI_CFG_DIR)')"
DOTA_DIR="$(python3 -c 'import os, config; print(os.path.dirname(config.SERVER_LOG_PATH))')"
if [ -d "$DOTA_DIR" ]; then
    mkdir -p "$GSI_DIR"
    cp -f gamestate_integration_dota_overlay.cfg "$GSI_DIR/"
    echo "Dota 2 найдена: $DOTA_DIR"
    echo "GSI-конфиг скопирован в: $GSI_DIR"
else
    echo "Папка Dota 2 не найдена автоматически (искал: $DOTA_DIR) - GSI-конфиг НЕ скопирован."
    echo "Проверь путь вручную в хабе (страница ОВЕРЛЕИ, карточка Драфт-статы)."
fi

echo ""
echo "Готово! Ищи «Dota Overlay Hub» в меню приложений."
echo "Или запусти прямо сейчас: python3 launcher.py"
