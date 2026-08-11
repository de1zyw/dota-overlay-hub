@echo off
setlocal enabledelayedexpansion

REM Prinuditelno perehodim v papku, gde lezhit sam etot skript. Bez etogo
REM esli fayl zapushen "ot imeni administratora" (UAC), Windows podstavlyaet
REM rabochey papkoy C:\Windows\System32 vmesto realnogo mesta skripta -
REM realnyy sluchay, poymanyy na zhivoy mashine: pyinstaller togda otkazyvalsya
REM rabotat pryamo v System32 s oshibkoy "Do not run pyinstaller from
REM C:\Windows\System32\...". %~dp0 vsegda ukazyvaet na papku samogo skripta
REM nezavisimo ot togo, kak i otkuda on zapushen.
cd /d "%~dp0"

REM Ves vyvod etogo skripta (i lyubye oshibki) avtomaticheski sohranyayutsya
REM v build_log.txt ryadom s etim faylom - eto nuzhno, chtoby pri lyuboy
REM probleme mozhno bylo prosto otpravit etot odin fayl, a ne peredavat na
REM slovah chto bylo na ekrane (okno konsoli pri dvoynom klike po .bat
REM zakryvaetsya srazu posle zaversheniya i ves tekst teryaetsya navsegda).
REM
REM Skript zapuskaet sam sebya povtorno (cherez "call") s redirektom vsego
REM vyvoda v etot log-fayl, zhdet zaversheniya, potom pokazyvaet ves log
REM na ekrane odnim kuskom i zhdet knopku pered zakrytiem - tak okno nikogda
REM ne zakroetsya samo soboy i nikakoy tekst ne propadet.
if not "%~1"=="~inner~" (
    echo ===============================================
    echo   Dota Overlay Hub - sborka .exe
    echo ===============================================
    echo.
    echo Zapuskayu sborku, eto mozhet zanyat neskolko minut.
    echo Ekran budet molchat pochti do samogo kontsa - eto normalno,
    echo NE ZAKRYVAY eto okno, prosto podozhdi.
    echo Ves protsess zapisyvaetsya v build_log.txt ryadom s etim faylom.
    echo.
    call "%~f0" ~inner~ > "%~dp0build_log.txt" 2>&1
    set "RESULT=!errorlevel!"
    echo.
    echo --------------- log sborki ^(build_log.txt^) ---------------
    type "%~dp0build_log.txt"
    echo ------------------------------------------------------------
    echo.
    if "!RESULT!"=="0" (
        echo ===============================================
        echo   Gotovo. "Dota Overlay Hub.exe" dolzhen lezhat
        echo   ryadom s etim skriptom.
        echo.
        echo   VAZHNO: Windows Defender/SmartScreen mozhet
        echo   pokazat preduprezhdenie pri pervom zapuske exe -
        echo   eto normalno dlya nepodpisannyh .exe, sobrannyh
        echo   iz Python. Zhmi "Podrobnee" -^> "Vse ravno zapustit".
        echo ===============================================
    ) else (
        echo ===============================================
        echo   OSHIBKA. Otpravte fayl build_log.txt ^(on lezhit
        echo   ryadom s etim skriptom^) tomu, kto prosil sobrat
        echo   programmu - tam polnyy tekst oshibki.
        echo ===============================================
    )
    pause
    exit /b !RESULT!
)

REM ============================================================
REM  Dalshe - realnaya rabota. Ee vyvod uhodit v build_log.txt,
REM  pauz zdes byt ne dolzhno (oni budut nevidimy i skript
REM  povisnet, molcha zhdya nazhatiya knopki, kotoruyu nikto ne
REM  uvidit) - vmesto etogo prosto exit /b 1 s soobsheniem v log.
REM ============================================================

REM Etot fayl mozhno otpravit odin, bez vsego proekta - esli ryadom net
REM launcher.py, on sam skachaet ves repozitoriy s GitHub i sobiraet
REM exe iznutri raspakovannoy papki, a gotovyy .exe polozhit ryadom s
REM etim samym build.bat (ne vnutri raspakovannoy papki).
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
            exit /b 1
        )
        powershell -NoProfile -Command "Expand-Archive -Path 'dota-overlay-hub.zip' -DestinationPath '.' -Force"
        if errorlevel 1 (
            echo [OSHIBKA] Ne udalos raspakovat proekt - fayl mog skachatsya povrezhdennym.
            echo Udali dota-overlay-hub.zip i zapusti build.bat snova.
            exit /b 1
        )
        del /q dota-overlay-hub.zip >nul 2>nul
    )
    cd dota-overlay-hub-master
)

REM Prostoy "where python" ne goditsya - na bolshinstve Windows 10/11 v PATH
REM po umolchaniyu est zaglushka Microsoft Store
REM (%LOCALAPPDATA%\Microsoft\WindowsApps\python.exe), kotoraya "nahoditsya",
REM no nichego realno ne delaet, esli nastoyashiy Python ne postavlen. Tekst
REM oshibki etoy zaglushki mozhet otlichatsya na raznyh Windows, poetomu ne
REM parsim tekst "--version" - prosto prosim Python realno vypolnit kod i
REM sveryaem tochnoe chislo na vyhode. Esli eto ne nastoyashiy Python - takogo
REM chisla prosto ne budet.
set "PY_OK="
for /f "delims=" %%V in ('python -c "print(offline_check_31337)" 2^>nul') do if "%%V"=="31337" set "PY_OK=1"
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
        exit /b 1
    )
    echo Ustanavlivayu Python ^(mozhet zanyat do minuty^)...
    "!PY_INSTALLER!" /quiet InstallAllUsers=0 PrependPath=1 Include_launcher=0 Include_test=0
    if errorlevel 1 (
        echo [OSHIBKA] Ustanovka Python zavershilas s oshibkoy.
        exit /b 1
    )
    del /q "!PY_INSTALLER!" >nul 2>nul
    REM Svezheustanovlennyy Python ne popadaet v PATH etoy uzhe otkrytoy konsoli
    REM (PrependPath pishet v reestr, no tekushiy protsess cmd.exe ego uzhe ne perechitaet) -
    REM dobavlyaem ego papku vruchnuyu na etu sessiyu.
    set "PYDIR="
    for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python3*") do set "PYDIR=%%D"
    if defined PYDIR set "PATH=!PYDIR!;!PYDIR!\Scripts;%PATH%"
    where python >nul 2>nul
    if errorlevel 1 (
        echo [OSHIBKA] Python ustanovlen, no ne viden v etoy sessii.
        echo Zapusti build.bat zanovo - on uzhe uvidit postavlennyy Python.
        exit /b 1
    )
    echo Python ustanovlen.
)

echo [2/5] Stavlyu zavisimosti...
python -m pip install --upgrade pip >nul
python -m pip install -r requirements.txt pyinstaller
if errorlevel 1 (
    echo [OSHIBKA] Ne udalos postavit zavisimosti - smotri tekst vyshe.
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
echo Vse shagi zaversheny uspeshno.
exit /b 0
