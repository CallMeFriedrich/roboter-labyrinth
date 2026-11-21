@echo off
rem ---------------------------------------------------------------------------
rem  Roboter-Labyrinth starten: Server + Besucher-Bildschirm im Kiosk-Modus.
rem
rem    start.bat            Kiosk-Vollbild auf dem Besucher-Monitor
rem    start.bat fenster    normales Browserfenster (zum Testen ohne 2. Monitor)
rem    start.bat server     nur der Server, kein Browser
rem
rem  Beenden: dieses Fenster schliessen oder Strg+C. Kiosk-Browser: Alt+F4.
rem ---------------------------------------------------------------------------
setlocal
cd /d "%~dp0"

rem Linke obere Ecke des Besucher-Monitors (2. Bildschirm rechts vom Laptop).
set "KIOSK_POSITION=1920,0"
set "PORT=8000"
rem 127.0.0.1 instead of localhost: no detour over IPv6, the page connects at once.
set "URL=http://127.0.0.1:%PORT%/"

if not exist ".venv\Scripts\python.exe" (
    echo Die Python-Umgebung fehlt. Bitte zuerst setup_windows.ps1 ausfuehren:
    echo     powershell -ExecutionPolicy Bypass -File setup_windows.ps1
    pause
    exit /b 1
)

if /i "%~1"=="server" goto server

rem Own browser profile: the kiosk flags also work while another Edge window is open.
set "PROFILE=%LOCALAPPDATA%\RoboterLabyrinth\kiosk-profile"
if /i "%~1"=="fenster" (
    set "MODE='--new-window','%URL%'"
) else (
    set "MODE='--kiosk','%URL%','--edge-kiosk-type=fullscreen','--window-position=%KIOSK_POSITION%'"
)
rem Open the browser 3 seconds after the server was started.
start "" /b powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 3; Start-Process msedge -ArgumentList %MODE%,'--no-first-run','--user-data-dir=\"%PROFILE%\"'"

:server
echo.
echo  Roboter-Labyrinth laeuft.
echo    Besucher:  %URL%
echo    Admin:     http://192.168.137.1:%PORT%/admin   (Tablet im Hotspot)
echo               http://localhost:%PORT%/admin       (auf diesem PC)
echo.
".venv\Scripts\python.exe" -m uvicorn app.main:app --host 0.0.0.0 --port %PORT% --no-access-log
echo.
echo Der Server wurde beendet.
pause
