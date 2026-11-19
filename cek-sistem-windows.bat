@echo off
setlocal EnableExtensions

REM ============================================================================
REM  Periksa apakah sistem dashboard sedang hidup, dan hidup dengan BENAR.
REM
REM  "Backend jalan" saja tidak cukup jadi jawaban. Bentuk kegagalan yang paling
REM  mahal di proyek ini justru backend yang jalan sempurna tapi tersambung ke
REM  broker MQTT yang salah: HTTP menjawab 200, log bilang "terhubung", perintah
REM  terbit tanpa error, dan papan tidak pernah menerimanya. Makanya skrip ini
REM  selalu menyebut NAMA BROKER-nya, bukan cuma "ok".
REM ============================================================================

cd /d "%~dp0"

if not defined API_PORT set "API_PORT=8000"
if not defined WEB_PORT set "WEB_PORT=5500"
if not defined BROKER_HARAPAN set "BROKER_HARAPAN=broker.hivemq.com:1883"

echo.
echo === Periksa sistem ACW ===
echo.

REM --- 1. PostgreSQL ----------------------------------------------------------
set "PGSVC="
for /f "tokens=2" %%S in ('sc query state^= all ^| findstr /I "SERVICE_NAME" ^| findstr /I "postgresql"') do set "PGSVC=%%S"
if not defined PGSVC (
    echo [X] PostgreSQL : layanannya tidak ditemukan
) else (
    sc query "%PGSVC%" | findstr /I "RUNNING" >nul 2>&1
    if errorlevel 1 (echo [X] PostgreSQL : %PGSVC% ADA tapi tidak jalan) else (echo [ok] PostgreSQL : %PGSVC% jalan)
)

REM --- 2. Ada yang mendengar di port backend? ----------------------------------
netstat -ano | findstr /R /C:"LISTENING" | findstr ":%API_PORT% " >nul 2>&1
if errorlevel 1 (
    echo [X] Backend    : tidak ada yang mendengar di port %API_PORT% - backend MATI
    echo.
    echo     Nyalakan dengan:  run-dashboard-windows.bat
    goto :frontend
)

REM Lebih dari satu pendengar di port yang sama itu MUNGKIN di Windows: 0.0.0.0
REM dan 127.0.0.1 bisa hidup berdampingan, dan permintaan "localhost" mendarat di
REM yang 127.0.0.1. Dua backend berarti yang kamu lihat belum tentu yang menjawab.
set /a JUMLAH=0
for /f %%C in ('netstat -ano ^| findstr /R /C:"LISTENING" ^| findstr ":%API_PORT% " ^| find /c /v ""') do set /a JUMLAH=%%C
if %JUMLAH% GTR 1 (
    echo [X] Backend    : ADA %JUMLAH% proses mendengar di port %API_PORT% sekaligus.
    echo                  Tutup semuanya lalu nyalakan satu saja - yang menjawab
    echo                  localhost belum tentu yang kamu kira.
    netstat -ano | findstr /R /C:"LISTENING" | findstr ":%API_PORT% "
)

REM --- 3. Backend benar-benar sehat? ------------------------------------------
REM Bukan cuma "port terbuka" - /health ikut menguji koneksi Postgres dan MQTT.
set "KESEHATAN="
for /f "delims=" %%H in ('curl.exe -s --max-time 5 http://127.0.0.1:%API_PORT%/health') do set "KESEHATAN=%%H"

if not defined KESEHATAN (
    echo [X] Backend    : port %API_PORT% terbuka tapi /health tidak menjawab
    goto :frontend
)

REM PID-nya ikut disebut. Backend TIDAK selalu punya jendela: proses yang
REM dinyalakan lepas dari induknya tetap hidup meski semua jendela ditutup, dan
REM "jalan" tanpa menyebut siapa cuma bikin bingung. Dengan PID-nya, matikan
REM dengan:  taskkill /PID <pid> /T /F
set "BEPID="
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:"LISTENING" ^| findstr ":%API_PORT% "') do set "BEPID=%%P"

echo [ok] Backend    : menjawab di port %API_PORT% ^(PID %BEPID%^)
echo      %KESEHATAN%

echo %KESEHATAN% | findstr /C:"\"db\":\"ok\"" >nul 2>&1
if errorlevel 1 (echo [X] Database   : backend TIDAK bisa menghubungi Postgres) else (echo [ok] Database   : terhubung)

echo %KESEHATAN% | findstr /C:"\"mqtt\":\"ok\"" >nul 2>&1
if errorlevel 1 (echo [X] MQTT       : TIDAK tersambung ke broker) else (echo [ok] MQTT       : tersambung)

REM Asisten AI itu tambahan - tanpa kunci, sisa dashboard tetap benar. Jadi ini
REM dilaporkan sebagai catatan, bukan sebagai kegagalan.
echo %KESEHATAN% | findstr /C:"\"ai\":\"ok\"" >nul 2>&1
if errorlevel 1 (
    echo [-] Asisten AI: tidak ada GEMINI_API_KEY - analisis ^& chat AI menjawab 503.
    echo                 Sisa dashboard tetap jalan normal. Kunci gratis:
    echo                 https://aistudio.google.com/apikey
) else (
    echo [ok] Asisten AI : kunci terpasang
)

echo %KESEHATAN% | findstr /C:"%BROKER_HARAPAN%" >nul 2>&1
if errorlevel 1 (
    echo [X] Broker     : BUKAN %BROKER_HARAPAN%
    echo                  Perintah dari dashboard tidak akan sampai ke papan.
    echo                  Tutup backend, lalu nyalakan lewat run-dashboard-windows.bat
    echo                  ^(jangan menjalankan main.py langsung tanpa MQTT_HOST^).
) else (
    echo [ok] Broker     : %BROKER_HARAPAN%
)

:frontend
REM --- 4. Server halaman dashboard --------------------------------------------
netstat -ano | findstr /R /C:"LISTENING" | findstr ":%WEB_PORT% " >nul 2>&1
if errorlevel 1 (
    echo [X] Dashboard  : tidak ada yang mendengar di port %WEB_PORT%
) else (
    echo [ok] Dashboard  : http://localhost:%WEB_PORT%
)

if defined BEPID (
    echo.
    echo      Backend tidak selalu punya jendela - proses yang dinyalakan lepas dari
    echo      induknya tetap hidup walau semua jendela sudah ditutup. Matikan dengan:
    echo        taskkill /PID %BEPID% /T /F
)

echo.
pause
endlocal
exit /b 0
