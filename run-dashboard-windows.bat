@echo off
setlocal EnableExtensions

REM ============================================================================
REM  Menjalankan dashboard di Windows tanpa Docker.
REM
REM  Setara dengan "docker compose up" versi Linux, tapi tiap bagian jalan
REM  langsung di mesin: PostgreSQL sebagai layanan Windows, backend di venv
REM  Python 3.11, frontend lewat server statis bawaan Python.
REM
REM  Kenapa Python 3.11 dan bukan yang terbaru: psycopg2-binary belum punya
REM  wheel untuk 3.13+, jadi pip akan mencoba kompilasi dari sumber dan gagal.
REM
REM  Semua variabel di bawah bisa ditimpa dari luar sebelum menjalankan skrip
REM  ini, misalnya:  set MQTT_HOST=broker-sendiri.local  &&  run-dashboard-windows.bat
REM ============================================================================

cd /d "%~dp0"

REM --- Konfigurasi (bawaan sama dengan README) --------------------------------
if not defined DB_HOST     set "DB_HOST=127.0.0.1"
if not defined DB_PORT     set "DB_PORT=5432"
if not defined DB_NAME     set "DB_NAME=smart_lights"
if not defined DB_USER     set "DB_USER=admin"
if not defined DB_PASSWORD set "DB_PASSWORD=ACW123"

if not defined MQTT_HOST   set "MQTT_HOST=broker.emqx.io"
if not defined MQTT_PORT   set "MQTT_PORT=1883"

if not defined API_HOST    set "API_HOST=127.0.0.1"
if not defined API_PORT    set "API_PORT=8000"
if not defined WEB_PORT    set "WEB_PORT=5500"

REM Venv sengaja di luar folder repo: isinya ribuan berkas kecil, dan folder ini
REM ada di OneDrive yang akan menyinkronkan semuanya terus-menerus.
if not defined VENV_DIR    set "VENV_DIR=%USERPROFILE%\.venvs\acw"

set "VPY=%VENV_DIR%\Scripts\python.exe"

echo.
echo === ACW Smart Lamp - menjalankan dashboard ===
echo.

REM --- 1. PostgreSQL harus hidup ---------------------------------------------
REM Nama layanannya ikut versi (postgresql-x64-17, -16, dst), jadi dicari dulu
REM daripada ditulis mati di sini.
set "PGSVC="
for /f "tokens=2" %%S in ('sc query state^= all ^| findstr /I "SERVICE_NAME" ^| findstr /I "postgresql"') do set "PGSVC=%%S"

if not defined PGSVC (
    echo [!] Layanan PostgreSQL tidak ditemukan.
    echo     Pasang dulu:  winget install --id PostgreSQL.PostgreSQL.17
    echo     Lalu buat database dan tabelnya dari python-backend\schema.sql
    goto :gagal
)

REM "sc query" menaruh kata RUNNING di kolom keempat barisnya, bukan ketiga -
REM lebih aman dicari langsung daripada dihitung kolomnya.
sc query "%PGSVC%" | findstr /I "RUNNING" >nul 2>&1
if errorlevel 1 (
    echo [*] %PGSVC% belum jalan, mencoba menyalakan...
    net start "%PGSVC%" >nul 2>&1
    if errorlevel 1 (
        echo [!] Gagal menyalakan %PGSVC%. Jalankan skrip ini sebagai administrator,
        echo     atau nyalakan layanannya lewat services.msc
        goto :gagal
    )
)
echo [ok] PostgreSQL jalan (%PGSVC%)

REM --- 2. Venv Python 3.11 -----------------------------------------------------
if not exist "%VPY%" (
    echo [*] Venv belum ada, membuat di %VENV_DIR%
    py -3.11 -m venv "%VENV_DIR%"
    if errorlevel 1 (
        echo [!] Python 3.11 tidak ditemukan.
        echo     Pasang dulu:  winget install --id Python.Python.3.11
        goto :gagal
    )
    echo [*] Memasang dependensi backend, sekali saja...
    "%VPY%" -m pip install --quiet --upgrade pip
    "%VPY%" -m pip install --quiet -r "python-backend\requirements.txt"
    if errorlevel 1 (
        echo [!] Gagal memasang dependensi. Lihat pesan di atas.
        goto :gagal
    )
)
echo [ok] Venv siap: %VENV_DIR%

REM --- 3. Backend --------------------------------------------------------------
echo [*] Menyalakan backend di port %API_PORT%
start "ACW backend (port %API_PORT%)" cmd /k ^
    "cd /d "%~dp0python-backend" && "%VPY%" main.py"

REM --- 4. Frontend -------------------------------------------------------------
echo [*] Menyalakan frontend di port %WEB_PORT%
start "ACW frontend (port %WEB_PORT%)" cmd /k ^
    "cd /d "%~dp0Dashboard_Monitoring" && "%VPY%" -m http.server %WEB_PORT% --bind 127.0.0.1"

REM Beri backend waktu membuka pool database sebelum browser meminta data.
timeout /t 5 /nobreak >nul

echo.
echo === Siap ===
echo   Dashboard   http://localhost:%WEB_PORT%
echo   API docs    http://localhost:%API_PORT%/docs
echo   Broker MQTT %MQTT_HOST%:%MQTT_PORT%
echo.
echo   Hentikan dengan menutup dua jendela "ACW backend" dan "ACW frontend".
echo.

start "" "http://localhost:%WEB_PORT%"
goto :selesai

:gagal
echo.
echo Gagal menjalankan. Perbaiki pesan di atas lalu coba lagi.
pause
exit /b 1

:selesai
endlocal
exit /b 0
