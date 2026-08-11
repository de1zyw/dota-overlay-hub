@echo off
setlocal

echo ===============================================
echo   Dota Overlay Hub - sborka .exe
echo ===============================================
echo.

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
echo [3/4] Perenoshu exe v papku s proektom...
move /y "dist\Dota Overlay Hub.exe" "Dota Overlay Hub.exe" >nul

echo [4/4] Chishu vremennye fayly sborki...
rmdir /s /q build >nul 2>nul
rmdir /s /q dist >nul 2>nul
del /q "Dota Overlay Hub.spec" >nul 2>nul

echo.
echo ===============================================
echo   Gotovo! Zapuskay "Dota Overlay Hub.exe"
echo.
echo   VAZHNO: Windows Defender/SmartScreen mozhet
echo   pokazat preduprezhdenie pri pervom zapuske -
echo   eto normalno dlya nepodpisannyh .exe, sobrannyh
echo   iz Python. Zhmi "Podrobnee" -^> "Vse ravno zapustit".
echo ===============================================
pause
