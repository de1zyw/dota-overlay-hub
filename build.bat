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
REM
REM VAZHNO: tekst zdes narochno na translite, ne na kirillitse - real'nyy
REM test na Windows pokazal, chto dazhe s "chcp 65001" cmd.exe u chasti
REM lyudey vse ravno lomaet parsing kirillicheskih echo-strok posredi
REM skripta (slova rvutsya, kuski slov vypolnyayutsya kak otdel'nye
REM komandy). ASCII - edinstvennyy variant, rabotayushiy garantirovanno
REM na lyuboy lokali/kodovoy stranitse. Ne vozvrashat kirillicu syuda bez
REM realnoy proverki na chistoy Windows-mashine.
set BOOTSTRAPPED=0
if not exist launcher.py (
    set BOOTSTRAPPED=1
    if not exist dota-overlay-hub-master\launcher.py (
        echo [0/5] Proekta ryadom net - skachivayu s GitHub...
        set "DL_FAIL="
        powershell -NoProfile -Command "$ProgressPreference='SilentlyContinue'; try { Invoke-WebRequest -Uri 'https://github.com/de1zyw/dota-overlay-hub/archive/refs/heads/master.zip' -OutFile 'dota-overlay-hub.zip' -UseBasicParsing } catch { exit 1 }"
        if errorlevel 1 set "DL_FAIL=1"
        if not exist dota-overlay-hub.zip set "DL_FAIL=1"
        if defined DL_FAIL (
            echo [OSHIBKA] Ne udalos skachat proekt. Proveryay internet-soedinenie i poprobuy snova.
            pause
            exit /b 1
        )
        powershell -NoProfile -Command "Expand-Archive -Path 'dota-overlay-hub.zip' -DestinationPath '.' -Force"
        if errorlevel 1 (
            echo [OSHIBKA] Ne udalos raspakovat proekt - fayl mog skachatsya povrezhdennym.
            echo Udali dota-overlay-hub.zip i zapusti build.bat snova.
            pause
            exit /b 1
        )
        del /q dota-overlay-hub.zip >nul 2>nul
    )
    cd dota-overlay-hub-master
)

REM Prostoy "where python" ne goditsya - na bolshinstve Windows 10/11 v PATH
REM po umolchaniyu est zaglushka Microsoft Store
REM (%LOCALAPPDATA%\Microsoft\WindowsApps\python.exe), kotoraya "nahoditsya",
REM no nichego realno ne delaet, esli nastoyashiy Python ne postavlen. Proveryaem
REM realnym zapuskom "python --version" i tem, chto otvet pohozh na versiyu.
set "PY_OK="
for /f "delims=" %%V in ('python --version 2^>^&1') do set "PY_LINE=%%V"
echo !PY_LINE! | findstr /r /c:"^Python 3\.[0-9]" >nul && set "PY_OK=1"
if not defined PY_OK (
    echo [1/5] Python ne nayden ^(ili eto pustaya zaglushka Microsoft Store^) - stavlyu nastoyashiy avtomaticheski ^(tikho, bez okon, prava administratora ne nuzhny^)...
    set "PY_URL=https://www.python.org/ftp/python/3.12.7/python-3.12.7-amd64.exe"
    set "PY_INSTALLER=python-installer.exe"
    set "DL_FAIL="
    powershell -NoProfile -Command "$ProgressPreference='SilentlyContinue'; try { Invoke-WebRequest -Uri '!PY_URL!' -OutFile '!PY_INSTALLER!' -UseBasicParsing } catch { exit 1 }"
    if errorlevel 1 set "DL_FAIL=1"
    if not exist "!PY_INSTALLER!" set "DL_FAIL=1"
    if defined DL_FAIL (
        echo [OSHIBKA] Ne udalos skachat Python. Proveryay internet-soedinenie ili
        echo postav vruchnuyu s https://www.python.org/downloads/ ^(galka "Add python.exe to PATH"^)
        echo i zapusti build.bat snova.
        pause
        exit /b 1
    )
    echo Ustanavlivayu Python ^(mozhet zanyat do minuty, okno ustanovki ne poyavitsya^)...
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
