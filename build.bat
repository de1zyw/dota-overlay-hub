@echo off
setlocal enabledelayedexpansion

echo ===============================================
echo   Dota Overlay Hub - sborka .exe
echo ===============================================
echo.

REM Etot fayl mozhno otpravit odin, bez vsego proekta - esli ryadom net
REM launcher.py, on sam skachaet ves repozitoriy s GitHub i sobiraet
REM exe iznutri raspakovannoy papki, a gotovyy .exe polozhit ryadom s
REM etim samym build.bat (ne vnutri raspakovannoy papki).
set BOOTSTRAPPED=0
if not exist launcher.py (
    set BOOTSTRAPPED=1
    if not exist dota-overlay-hub-master\launcher.py (
        echo [0/4] Proekta ryadom net - skachivayu s GitHub...
        powershell -NoProfile -Command "Invoke-WebRequest -Uri 'https://github.com/de1zyw/dota-overlay-hub/archive/refs/heads/master.zip' -OutFile 'dota-overlay-hub.zip'"
        if errorlevel 1 (
            echo [OSHIBKA] Ne udalos skachat proekt. Proveryay internet-soedinenie.
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
    echo [OSHIBKA] Python ne nayden v PATH.
    echo Skachay i postav s https://www.python.org/downloads/
    echo Pri ustanovke OBYAZATELNO otmet "Add python.exe to PATH"
    pause
    exit /b 1
)

echo [1/4] Stavlyu zavisimosti...
python -m pip install --upgrade pip >nul
python -m pip install -r requirements.txt pyinstaller
if errorlevel 1 (
    echo [OSHIBKA] Ne udalos postavit zavisimosti - smotri tekst vyshe.
    pause
    exit /b 1
)

echo.
echo [2/4] Sobirayu .exe (mozhet zanyat paru minut)...
REM Bez --windowed narochno: konsol ostaetsya vidna, chtoby pri lyuboy
REM oshibke pri zapuske byl viden nastoyashiy tekst oshibki, a ne prosto
REM tishina. Ubrat --windowed mozhno pozzhe, kogda vse proveryeno.
python -m PyInstaller --noconfirm --onefile ^
  --name "Dota Overlay Hub" ^
  --icon icon.ico ^
  --add-data "assets;assets" ^
  --add-data "icon.png;." ^
  --add-data "gamestate_integration_dota_overlay.cfg;." ^
  launcher.py

if errorlevel 1 (
    echo [OSHIBKA] Sborka ne udalas, smotri tekst vyshe.
    pause
    exit /b 1
)

echo.
echo [3/4] Perenoshu exe...
if "%BOOTSTRAPPED%"=="1" (
    move /y "dist\Dota Overlay Hub.exe" "..\Dota Overlay Hub.exe" >nul
) else (
    move /y "dist\Dota Overlay Hub.exe" "Dota Overlay Hub.exe" >nul
)

echo [4/4] Chishu vremennye fayly sborki...
rmdir /s /q build >nul 2>nul
rmdir /s /q dist >nul 2>nul
del /q "Dota Overlay Hub.spec" >nul 2>nul

if "%BOOTSTRAPPED%"=="1" cd ..

echo.
echo ===============================================
echo   Gotovo! "Dota Overlay Hub.exe" lezhit ryadom
echo   s etim skriptom.
echo.
echo   VAZHNO: Windows Defender/SmartScreen mozhet
echo   pokazat preduprezhdenie pri pervom zapuske -
echo   eto normalno dlya nepodpisannyh .exe, sobrannyh
echo   iz Python. Zhmi "Podrobnee" -^> "Vse ravno zapustit".
echo ===============================================
pause
