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
        echo [0/5] Proekta ryadom net - skachivayu s GitHub...
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
    echo [1/5] Python ne nayden - stavlyu avtomaticheski ^(tikho, bez okon, ne nuzhny prava administratora^)...
    set "PY_URL=https://www.python.org/ftp/python/3.12.7/python-3.12.7-amd64.exe"
    set "PY_INSTALLER=python-installer.exe"
    powershell -NoProfile -Command "Invoke-WebRequest -Uri '!PY_URL!' -OutFile '!PY_INSTALLER!'"
    if errorlevel 1 (
        echo [OSHIBKA] Ne udalos skachat Python. Proveryay internet-soedinenie ili
        echo postav vruchnuyu s https://www.python.org/downloads/ ^(galka "Add python.exe to PATH"^)
        echo i zapusti build.bat snova.
        pause
        exit /b 1
    )
    echo Ustanavlivayu Python ^(mozhet zanyat do minuty, okno ustanovki ne pokazhetsya^)...
    "!PY_INSTALLER!" /quiet InstallAllUsers=0 PrependPath=1 Include_launcher=0 Include_test=0
    if errorlevel 1 (
        echo [OSHIBKA] Ustanovka Python zavershilas s oshibkoy.
        pause
        exit /b 1
    )
    del /q "!PY_INSTALLER!" >nul 2>nul
    REM Svezheustanovlennyy Python ne popadaet v PATH etoy uzhe otkrytoy konsoli
    REM (PrependPath pishet v reestr, no tekushiy protsess cmd.exe ego uzhe ne perechitaet) -
    REM dobavlyaem ego papku vruchnuyu na etu sessiyu, chtoby ne prosit perezapustit skript.
    set "PYDIR="
    for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python3*") do set "PYDIR=%%D"
    if defined PYDIR set "PATH=!PYDIR!;!PYDIR!\Scripts;%PATH%"
    where python >nul 2>nul
    if errorlevel 1 (
        echo [OSHIBKA] Python ustanovlen, no ne viden v etom okne.
        echo Zakroy eto okno i zapusti build.bat zanovo - on uzhe uvidit postavlennyy Python.
        pause
        exit /b 1
    )
    echo Python ustanovlen.
)

echo [2/5] Stavlyu zavisimosti...
python -m pip install --upgrade pip >nul
python -m pip install -r requirements.txt pyinstaller
if errorlevel 1 (
    echo [OSHIBKA] Ne udalos postavit zavisimosti - smotri tekst vyshe.
    pause
    exit /b 1
)

echo.
echo [3/5] Sobirayu .exe (mozhet zanyat paru minut)...
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
echo [4/5] Perenoshu exe...
if "%BOOTSTRAPPED%"=="1" (
    move /y "dist\Dota Overlay Hub.exe" "..\Dota Overlay Hub.exe" >nul
) else (
    move /y "dist\Dota Overlay Hub.exe" "Dota Overlay Hub.exe" >nul
)

echo [5/5] Chishu vremennye fayly sborki...
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
