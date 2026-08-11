@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

echo ===============================================
echo   Dota Overlay Hub - сборка .exe
echo ===============================================
echo.

REM Этот файл можно отправить один, без всего проекта - если рядом нет
REM launcher.py, он сам скачает весь репозиторий с GitHub и соберёт
REM exe изнутри распакованной папки, а готовый .exe положит рядом с
REM этим самым build.bat (не внутри распакованной папки).
set BOOTSTRAPPED=0
if not exist launcher.py (
    set BOOTSTRAPPED=1
    if not exist dota-overlay-hub-master\launcher.py (
        echo [0/5] Проекта рядом нет - скачиваю с GitHub...
        powershell -NoProfile -Command "Invoke-WebRequest -Uri 'https://github.com/de1zyw/dota-overlay-hub/archive/refs/heads/master.zip' -OutFile 'dota-overlay-hub.zip'"
        if errorlevel 1 (
            echo [ОШИБКА] Не удалось скачать проект. Проверяй интернет-соединение.
            pause
            exit /b 1
        )
        powershell -NoProfile -Command "Expand-Archive -Path 'dota-overlay-hub.zip' -DestinationPath '.' -Force"
        del /q dota-overlay-hub.zip >nul 2>nul
    )
    cd dota-overlay-hub-master
)

where python >nul 2>nul
if errorlevel 1 (
    echo [1/5] Python не найден - ставлю автоматически ^(тихо, без окон, права администратора не нужны^)...
    set "PY_URL=https://www.python.org/ftp/python/3.12.7/python-3.12.7-amd64.exe"
    set "PY_INSTALLER=python-installer.exe"
    powershell -NoProfile -Command "Invoke-WebRequest -Uri '!PY_URL!' -OutFile '!PY_INSTALLER!'"
    if errorlevel 1 (
        echo [ОШИБКА] Не удалось скачать Python. Проверяй интернет-соединение или
        echo поставь вручную с https://www.python.org/downloads/ ^(галка "Add python.exe to PATH"^)
        echo и запусти build.bat снова.
        pause
        exit /b 1
    )
    echo Устанавливаю Python ^(может занять до минуты, окно установки не появится^)...
    "!PY_INSTALLER!" /quiet InstallAllUsers=0 PrependPath=1 Include_launcher=0 Include_test=0
    if errorlevel 1 (
        echo [ОШИБКА] Установка Python завершилась с ошибкой.
        pause
        exit /b 1
    )
    del /q "!PY_INSTALLER!" >nul 2>nul
    REM Свежеустановленный Python не попадает в PATH этой уже открытой консоли
    REM (PrependPath пишет в реестр, но текущий процесс cmd.exe его уже не перечитает) -
    REM добавляем его папку вручную на эту сессию, чтобы не просить перезапустить скрипт.
    set "PYDIR="
    for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python3*") do set "PYDIR=%%D"
    if defined PYDIR set "PATH=!PYDIR!;!PYDIR!\Scripts;%PATH%"
    where python >nul 2>nul
    if errorlevel 1 (
        echo [ОШИБКА] Python установлен, но не виден в этом окне.
        echo Закрой это окно и запусти build.bat заново - он уже увидит поставленный Python.
        pause
        exit /b 1
    )
    echo Python установлен.
)

echo [2/5] Ставлю зависимости...
python -m pip install --upgrade pip >nul
python -m pip install -r requirements.txt pyinstaller
if errorlevel 1 (
    echo [ОШИБКА] Не удалось поставить зависимости - смотри текст выше.
    pause
    exit /b 1
)

echo.
echo [3/5] Собираю .exe (может занять пару минут)...
REM Без --windowed нарочно: консоль остаётся видна, чтобы при любой
REM ошибке при запуске был виден настоящий текст ошибки, а не просто
REM тишина. Убрать --windowed можно позже, когда всё проверено.
python -m PyInstaller --noconfirm --onefile ^
  --name "Dota Overlay Hub" ^
  --icon icon.ico ^
  --add-data "assets;assets" ^
  --add-data "icon.png;." ^
  --add-data "gamestate_integration_dota_overlay.cfg;." ^
  launcher.py

if errorlevel 1 (
    echo [ОШИБКА] Сборка не удалась, смотри текст выше.
    pause
    exit /b 1
)

echo.
echo [4/5] Переношу exe...
if "%BOOTSTRAPPED%"=="1" (
    move /y "dist\Dota Overlay Hub.exe" "..\Dota Overlay Hub.exe" >nul
) else (
    move /y "dist\Dota Overlay Hub.exe" "Dota Overlay Hub.exe" >nul
)

echo [5/5] Чищу временные файлы сборки...
rmdir /s /q build >nul 2>nul
rmdir /s /q dist >nul 2>nul
del /q "Dota Overlay Hub.spec" >nul 2>nul

if "%BOOTSTRAPPED%"=="1" cd ..

echo.
echo ===============================================
echo   Готово! "Dota Overlay Hub.exe" лежит рядом
echo   с этим скриптом.
echo.
echo   ВАЖНО: Windows Defender/SmartScreen может
echo   показать предупреждение при первом запуске -
echo   это нормально для неподписанных .exe, собранных
echo   из Python. Жми "Подробнее" -^> "Всё равно запустить".
echo ===============================================
pause
