# Smart Lamp System - City Manager Dashboard

Dashboard Monitoring dan Manajemen Sistem Penerangan Jalan Pintar (Smart Street Lighting) berbasis Web Real-Time. Backend satu proses **Python/FastAPI** menangani REST API, WebSocket, ingest telemetri MQTT, dan evaluasi peringatan otomatis; frontend memvisualisasikan posisi lampu di peta 3D, kendali manual, penjadwalan RTC per sektor, riwayat telemetri, kotak peringatan, dan asisten AI (Gemini) yang menjawab pertanyaan berdasarkan data live di database - bukan jawaban karangan.

---

## 🎯 Ringkasan Eksekutif

**Masalah:** Penerangan jalan kota umumnya dipantau manual (laporan warga, patroli fisik) - lampu mati atau boros daya baru ketahuan berhari-hari kemudian, tidak ada data historis buat perencanaan.

**Solusi:** Tiap tiang lampu (ESP32 + modem seluler) kirim data tegangan/arus/daya real-time lewat MQTT ke satu dashboard terpusat. Sistem otomatis mengevaluasi kesehatan tiap lampu, memicu peringatan begitu ada anomali (lonjakan tegangan, lampu offline, arus abnormal), dan menyimpan riwayat penuh untuk analisis tren maupun estimasi usia pakai.

**Diferensiator:**
* Data & analisis **live dari database sungguhan** - termasuk asisten AI, tidak ada angka karangan.
* Kendali **dua arah**: dashboard bisa kirim perintah balik ke lampu (kecerahan, jadwal RTC), bukan cuma baca data.
* Dibangun dengan **keamanan sebagai bagian inti**, bukan tempelan - hashing password modern, proteksi brute-force, pembatasan akses berlapis (lihat bagian Keamanan).

---

## 🚀 Fitur Utama

### 1. Dashboard - Ringkasan Sistem
Halaman beranda, agregat **seluruh sistem** (bukan per lampu):
* Kartu KPI: total lampu, total daya aktif, rata-rata tegangan & arus, jumlah peringatan belum dibaca.
* Grafik rata-rata telemetri (tegangan/arus/daya) seluruh lampu, dikelompokkan per jam.
* Dua diagram donat: kesehatan lampu (Sehat/Perlu Perhatian/Perlu Perawatan) dan pembagian jumlah lampu per sektor, dengan rincian per sektor di bawahnya.
* **Ringkasan AI Sistem** - analisis naratif kondisi keseluruhan sistem (tombol manual, hasil di-cache).

### 2. Monitor Lampu - Detail Per Perangkat
Pemantauan satu lampu yang dipilih dari dropdown:
* Status kesehatan, estimasi usia pakai (progress bar terhadap 10.000 jam), daya/tegangan/arus real-time, koordinat GPS.
* Grafik tren daya terbaru + badge persentase perubahan.
* **Ringkasan AI per lampu** (tombol manual).
* Kendali Cepat (Manual Override): slider kecerahan (dimming) dan kehangatan warna (CCT), terkunci di belakang toggle keamanan - khusus admin.
* Peta 3D (Maplibre GL + OpenFreeMap) dengan panel detail lampu yang bisa dibuka per pin.

### 3. Kelola Lampu - Penjadwalan RTC per Sektor (khusus admin)
* Jadwal kecerahan & kehangatan warna murni per sektor (bukan per lampu individu) - berlaku untuk semua lampu dalam sektor terpilih.
* Default 3 fase, admin bisa menambah sampai maksimal 6 fase, atau menghapus kembali ke minimum 3.
* Jadwal tersimpan permanen ke database dan di-push ke tiap lampu fisik lewat MQTT (retained) saat disimpan - firmware ESP32 (modul RTC DS3231) yang mengeksekusi tiap fase secara mandiri sesuai jamnya sendiri.

### 4. Riwayat Data - Telemetri per Sektor
* Pilih sektor, semua lampu di dalamnya ditampilkan sekaligus (scroll), masing-masing dengan kartu ringkasan rata-rata + grafik tegangan/arus/daya dari riwayat asli di database.
* **Analisis AI per lampu** - tombol per kartu, menyimpulkan kondisi lampu berdasarkan riwayat telemetrinya.

### 5. Kotak Peringatan
* Daftar peringatan (lonjakan tegangan, perangkat offline, lonjakan arus, perangkat tak terdaftar) dengan filter tingkat keparahan, sektor/lampu, dan pencarian teks.
* Tandai dibaca (semua role) dan hapus (khusus admin) - aksi hapus lewat modal konfirmasi, bukan langsung eksekusi.

### 6. Asisten AI Dasbor
Widget chat mengambang di seluruh halaman - jawab pertanyaan bebas soal data sistem lewat tool-calling ke Gemini (cek daftar lampu, riwayat telemetri, atau riwayat peringatan sesuai kebutuhan pertanyaan), jawaban di-stream dan digrounding ke database, tidak mengarang angka.

### 7. Autentikasi & Peran
* Login dengan sesi berbasis token (12 jam), hash password Argon2id (auto-upgrade dari hash lama saat login berhasil).
* Dua peran: **admin** (akses penuh, termasuk Kelola Lampu, Kendali Cepat, hapus peringatan) dan **petugas monitoring** (baca-saja - halaman & aksi admin disembunyikan dan ditolak juga di sisi backend).

### 8. Tema Tampilan
* Dua tema: default dan **Onyx** (gelap-glossy) - bisa ganti kapan saja lewat tombol di sidebar maupun halaman login, tersimpan per perangkat, langsung berlaku tanpa kedip saat halaman dimuat ulang.

---

## 🔒 Keamanan

Dibangun berlapis, bukan satu gerbang tunggal:
* **Password**: hash Argon2id, tanpa penyimpanan plaintext di mana pun.
* **Anti brute-force login**: pembatasan laju berbasis IP + penguncian sementara dengan hitung mundur yang tampil ke pengguna; percobaan login gagal berturut-turut memicu peringatan real-time ke semua admin yang sedang login.
* **Anti pembocoran username**: waktu respons login dibuat konsisten (timing-safe) - lawan menebak akun valid lewat selisih waktu respons.
* **Whitelist perangkat**: `device_id` yang belum terdaftar ditolak total (data tidak disimpan), bukan auto-register - mencegah data lampu palsu menyusup ke sistem.
* **Validasi bentuk `device_id` ketat** di titik masuk MQTT maupun saat pendaftaran - menutup celah suntik markup/injeksi lewat nama perangkat.
* **Header keamanan browser** (CSP, dsb.) di dashboard, mencegah eksekusi skrip asing meski ada celah lain.
* **Sesi bisa dicabut**: logout langsung membatalkan token di server, bukan cuma hapus di sisi klien.
* **Query terparameterisasi** ke PostgreSQL di seluruh backend - tidak ada string SQL rakitan manual.
* **Pembatasan laju** terpisah untuk tiap jenis endpoint (publik, tulis-admin, asisten AI) - satu klien tidak bisa menghabiskan kapasitas server buat yang lain.

---

## ⚙️ Keandalan & Kualitas Kode

* **`GET /health`** - endpoint pemeriksaan kesehatan (server + koneksi database), dipakai orkestrator/monitoring buat tahu server siap menerima trafik.
* **Kontrak respons API tertip** - tiap endpoint JSON punya skema respons eksplisit (Pydantic `response_model`), kesalahan bentuk data ketahuan saat pengembangan, bukan muncul diam-diam di produksi.
* **Broadcast WebSocket paralel** - update ke banyak dashboard yang terhubung dikirim bersamaan, satu koneksi klien yang lambat tidak menahan update ke klien lain.
* **CI otomatis** (GitHub Actions) - tiap perubahan kode dites otomatis (`pytest` backend, `vitest` frontend) sebelum masuk ke branch utama.
* **Pool koneksi database** dengan retry - menahan lonjakan permintaan bersamaan tanpa kehabisan koneksi.

---

## 🧪 Pengujian

* **Simulator lampu** (`python-backend/tools/simulate_light.py`) - berperan sebagai ESP32 sungguhan lewat MQTT (topic sama persis), dipakai buat menguji seluruh alur sistem (ingest telemetri, evaluasi peringatan, kendali dua arah, jadwal RTC) tanpa perlu hardware fisik menyala.
* Skenario teruji: telemetri normal, lonjakan tegangan, perangkat offline, lonjakan arus, perangkat tak terdaftar, `device_id` tidak valid, kendali kecerahan dari dashboard ke lampu, dan push jadwal RTC.
* Detail lengkap tiap skenario & cara verifikasi: `python-backend/tools/TESTING.md`.

---

## 🛠️ Teknologi yang Digunakan

| Lapisan | Teknologi |
|---|---|
| Frontend | HTML5, Vanilla CSS3 (dark theme, custom dropdown & modal dengan transisi), JavaScript (ES6, tanpa framework/build step) |
| Peta 3D | Maplibre GL + OpenFreeMap |
| Grafik | Chart.js |
| Backend | Python 3.11, FastAPI (REST + WebSocket dalam satu proses), Uvicorn |
| Database | PostgreSQL (koneksi lewat psycopg2, connection pool) |
| Ingest IoT | MQTT (paho-mqtt) - subscribe telemetri, publish command/jadwal ke ESP32 |
| Autentikasi | Argon2id (argon2-cffi), sesi token in-memory |
| Asisten AI | Google Gemini, lewat endpoint OpenAI-compatible resminya (httpx) |
| Reverse proxy (produksi) | Caddy (TLS otomatis Let's Encrypt, lihat `Caddyfile`) |

---

## 📂 Struktur Repositori

```bash
Dashboard_Monitoring/
├── index.html          # Struktur seluruh halaman (Dashboard, Monitor, Kelola, Riwayat, Peringatan)
├── style.css            # Tema gelap, komponen custom (dropdown/modal + transisi), layout responsif
└── script.js            # Navigasi SPA, WebSocket, Chart.js, Maplibre GL, state & sinkronisasi

python-backend/
├── main.py               # Entrypoint FastAPI - daftar semua router, startup (DB pool, MQTT, WS)
├── config.py              # Semua konfigurasi dari environment variable
├── db.py                  # Query PostgreSQL (parameterized)
├── mqtt_ingest.py         # Subscribe telemetri MQTT, evaluasi alert, publish command/jadwal
├── auth.py                 # Hashing password (Argon2id) & sesi token
├── alerts.py                # Aturan klasifikasi kesehatan & threshold peringatan
├── ai_chat.py                # Integrasi Gemini: chat tool-calling, analisis per-lampu & per-sistem
├── ws_manager.py              # Broadcast WebSocket ke semua dashboard yang terhubung
├── routes_devices.py           # GET /api/devices-latest, /api/telemetry-history
├── routes_overview.py           # GET /api/system-overview (agregat Dashboard)
├── routes_schedules.py           # GET/PUT /api/sector-schedules
├── routes_command.py              # POST /api/lights/:id/command (kendali cepat)
├── routes_alerts.py                # CRUD /api/alerts*
├── routes_auth.py                   # POST /api/login
├── routes_chat.py                    # POST /api/chat, /api/chat/analyze-device, /api/chat/analyze-system
├── schema.sql                         # Cetak biru struktur database - lihat SCHEMA_README.md
├── SCHEMA_README.md                    # Cara pakai schema.sql & cara menjaganya tetap akurat
├── requirements.txt
└── Dockerfile

Caddyfile                # Reverse proxy TLS untuk deployment produksi (opsional)
run-dashboard-windows.bat # Menjalankan backend + frontend di Windows tanpa Docker
```

---

## ⚙️ Persiapan & Jalankan Lokal

### 1. Prasyarat
* PostgreSQL dengan tabel `devices`, `sectors`, `telemetry_logs`, `alerts`, `users`, `sector_schedules` sudah dibuat.
* Broker MQTT (mis. Mosquitto atau `broker.emqx.io` publik) untuk lalu lintas telemetri ESP32.
* Python 3.11 atau 3.12 - **bukan 3.13+**, karena `psycopg2-binary` belum menyediakan wheel untuk versi itu dan pemasangannya akan gagal saat mencoba kompilasi dari sumber.
* (Opsional) API key Gemini dari [Google AI Studio](https://aistudio.google.com/apikey) untuk fitur asisten AI - tanpa ini, semua fitur non-AI tetap berjalan normal, endpoint chat/analisis akan balikin 503.

### 2. Konfigurasi Environment Variable

| Variabel | Default | Keterangan |
|---|---|---|
| `DB_HOST` / `DB_PORT` / `DB_NAME` / `DB_USER` / `DB_PASSWORD` | `postgres_db` / `5432` / `smart_lights` / `admin` / `ACW123` | Koneksi PostgreSQL |
| `MQTT_HOST` / `MQTT_PORT` | `broker.emqx.io` / `1883` | Broker MQTT |
| `MQTT_TELEMETRY_TOPIC` | `iot/lights/+/telemetry` | Topic subscribe telemetri |
| `API_HOST` / `API_PORT` | `0.0.0.0` / `8000` | Alamat listen server |
| `SESSION_DURATION_HOURS` | `12` | Masa berlaku sesi login |
| `CORS_ALLOW_ORIGINS` | `*` | Origin yang diizinkan akses API |
| `GEMINI_API_KEY` | *(kosong)* | Wajib diisi untuk fitur asisten AI |
| `GEMINI_MODEL` | `gemini-flash-lite-latest` | Model Gemini yang dipakai |

Jangan pernah taruh `GEMINI_API_KEY` atau kredensial database langsung di source code - selalu lewat environment variable.

### 3. Menjalankan Backend

```bash
cd python-backend
pip install -r requirements.txt
export DB_HOST=localhost DB_PASSWORD=... GEMINI_API_KEY=...   # sesuaikan
python3 main.py
```

Atau lewat Docker:

```bash
cd python-backend
docker build -t acw-backend .
docker run -p 8000:8000 --env-file .env acw-backend
```

Dokumentasi API otomatis (Swagger UI) tersedia di `http://localhost:8000/docs` setelah server jalan.

### 4. Menjalankan Frontend

Dashboard adalah HTML/CSS/JS murni tanpa build step - buka lewat server statis apa saja:

```bash
cd Dashboard_Monitoring
python3 -m http.server 5500
```

Buka `http://localhost:5500`. Frontend otomatis menurunkan alamat backend dari hostname halaman itu sendiri (`http://<host>:8000`) - jadi kalau dashboard diakses dari perangkat lain di jaringan yang sama, tidak perlu ubah konfigurasi apa pun.

### 5. Menjalankan di Windows (tanpa Docker)

Docker tidak wajib. Semua bagian bisa jalan langsung di Windows: PostgreSQL sebagai layanan, backend di virtualenv, frontend lewat server statis bawaan Python. Setelah persiapan sekali di bawah selesai, cukup klik dua kali `run-dashboard-windows.bat` di akar repo.

#### 5.1 Pasang prasyarat

```powershell
winget install --id PostgreSQL.PostgreSQL.17 --override "--mode unattended --superpassword ACW123 --serverport 5432"
winget install --id Python.Python.3.11
```

Pemasangan PostgreSQL memunculkan prompt administrator. Setelah selesai, layanan `postgresql-x64-17` otomatis jalan dan ikut menyala tiap boot.

**Python harus 3.11, bukan yang terbaru.** `psycopg2-binary` belum menyediakan wheel untuk Python 3.13+, sehingga `pip install` akan mencoba mengompilasi dari sumber dan gagal. Versi lain boleh tetap terpasang di mesin - skrip menjalankan `py -3.11` secara eksplisit.

#### 5.2 Buat database dan tabelnya

```powershell
$env:PGPASSWORD = "ACW123"
$psql = "C:\Program Files\PostgreSQL\17\bin\psql.exe"

& $psql -U postgres -h 127.0.0.1 -c "CREATE ROLE admin LOGIN PASSWORD 'ACW123' SUPERUSER;"
& $psql -U postgres -h 127.0.0.1 -c "CREATE DATABASE smart_lights OWNER admin;"
& $psql -U admin -h 127.0.0.1 -d smart_lights -f python-backend\schema.sql
& $psql -U admin -h 127.0.0.1 -d smart_lights -f python-backend\schema_indexes.sql
```

`schema_indexes.sql` akan memberi beberapa `NOTICE: relation ... already exists, skipping` - itu wajar, sebagian index sudah dibuat oleh `schema.sql`.

#### 5.3 Buat akun login pertama

`schema.sql` hanya memindahkan **bentuk** tabel, bukan isinya. Database yang baru dibuat kosong sama sekali, termasuk tabel `users` - jadi akun dari instalasi lama tidak ikut pindah, dan login apa pun akan ditolak sampai akun dibuat di sini.

```powershell
py -3.11 -m venv "$env:USERPROFILE\.venvs\acw"
$vpy = "$env:USERPROFILE\.venvs\acw\Scripts\python.exe"
& $vpy -m pip install -r python-backend\requirements.txt

cd python-backend
$hash = & $vpy -c "import auth; print(auth.hash_password('ACW123'))"
cd ..

$env:PGPASSWORD = "ACW123"
& $psql -U admin -h 127.0.0.1 -d smart_lights -c "INSERT INTO users (username, password_hash, role) VALUES ('admin', '$hash', 'admin');"
```

Hasilnya: `admin` / `ACW123` dengan peran admin. Ganti kata sandinya sebelum dipakai di luar mesin pengembangan.

#### 5.4 Jalankan

```
run-dashboard-windows.bat
```

Skrip ini menyalakan layanan PostgreSQL bila tertidur, membuat virtualenv beserta dependensinya bila belum ada, menjalankan backend di `:8000` dan frontend di `:5500`, lalu membuka browser. Dua jendela terminal akan terbuka - tutup keduanya untuk menghentikan.

Semua variabel di [bagian 2](#2-konfigurasi-environment-variable) bisa ditimpa sebelum menjalankan:

```powershell
$env:MQTT_HOST = "broker-sendiri.local"
.\run-dashboard-windows.bat
```

#### 5.5 Pastikan berjalan normal

```powershell
curl http://localhost:8000/health
# {"status":"ok","db":"ok"}
```

Lalu buka `http://localhost:5500` dan login. Dashboard akan terbuka dalam keadaan kosong - belum ada sektor maupun lampu.

#### 5.6 Daftarkan sektor dan perangkat

Lewat menu onboarding di dashboard, atau lewat API:

```powershell
$tok = (Invoke-RestMethod -Uri http://localhost:8000/api/login -Method Post `
        -ContentType "application/json" `
        -Body '{"username":"admin","password":"ACW123"}').token

$h = @{ "X-ACW-Token" = $tok; "Content-Type" = "application/json" }

Invoke-RestMethod -Uri http://localhost:8000/api/sectors -Method Post -Headers $h `
  -Body '{"sector_name":"Sektor 2 (Kertajaya - Depan ITS)"}'

Invoke-RestMethod -Uri http://localhost:8000/api/devices -Method Post -Headers $h `
  -Body '{"device_id":"NEMA-01","sector_name":"Sektor 2 (Kertajaya - Depan ITS)","lat":-7.314997,"lng":112.789502}'
```

Urutannya tidak bisa dibalik: `device_id` yang belum terdaftar **ditolak total** di ingest MQTT - datanya tidak disimpan, dan dashboard justru menerima peringatan "perangkat tak dikenal". Daftarkan perangkat sebelum ia mulai mengirim.

#### 5.7 Uji jalur telemetri dari ujung ke ujung

```powershell
& $vpy -c @"
import json, paho.mqtt.client as mqtt, time
c = mqtt.Client(client_id='probe'); c.connect('broker.emqx.io', 1883, 30); c.loop_start()
c.publish('iot/lights/NEMA-01/telemetry', json.dumps({
    'id':'NEMA-01','volt':219.1,'current':0.756,'power':161.5,'uptime':3600,'dim':100}), qos=1)
time.sleep(3); c.loop_stop(); c.disconnect()
"@
```

Lampu akan muncul di peta dan dropdown Monitor Lampu tanpa perlu memuat ulang halaman - datanya didorong lewat WebSocket. Kalau muncul, berarti seluruh rantai broker -> ingest -> PostgreSQL -> WebSocket -> dashboard sudah hidup.

#### 5.8 Kalau ada yang tidak beres

| Gejala | Sebab | Tindakan |
|---|---|---|
| Login ditolak (401) padahal kata sandi benar | Database baru, tabel `users` kosong | Ulangi langkah 5.3 |
| `pip install` gagal di `psycopg2-binary` | Dijalankan dengan Python 3.13+ | Pakai virtualenv Python 3.11 seperti di 5.3 |
| Backend gagal konek database | Variabel `DB_HOST` masih `postgres_db`, nama container Docker | Jalankan lewat `run-dashboard-windows.bat` yang sudah menyetelnya ke `127.0.0.1` |
| Dashboard terbuka tapi semua data kosong | Backend di `:8000` tidak jalan | Cek jendela "ACW backend", dan `curl http://localhost:8000/health` |
| Telemetri terkirim tapi tidak muncul | `device_id` belum terdaftar | Ulangi langkah 5.6, lalu cek Kotak Peringatan |

#### 5.9 Perbedaan dari penyiapan Docker

| | Docker (Linux) | Windows |
|---|---|---|
| Alamat antar layanan | Nama container (`postgres_db`) | `127.0.0.1` dan nomor port |
| Umur data | Hilang bila volume dihapus | Menetap di direktori data PostgreSQL |
| Menyalakan | `docker compose up` | `run-dashboard-windows.bat` |
| Frontend | Disajikan Caddy, satu port | Server statis terpisah di `:5500` |
| Python | Dibawa image | Virtualenv 3.11 di `%USERPROFILE%\.venvs\acw` |

Broker MQTT tidak berubah: bawaannya tetap `broker.emqx.io` yang publik, bukan Mosquitto lokal, baik di Docker maupun di sini. Broker publik itu tanpa autentikasi - siapa pun yang tahu sebuah `device_id` dapat mengirim perintah ke topik `iot/lights/<device_id>/command`. Cukup untuk pengembangan, tetapi ganti ke broker berautentikasi sebelum dipasang di lapangan; cukup lewat `MQTT_HOST` dan `MQTT_PORT`, tanpa mengubah kode.

---

## 🔌 Ringkasan Endpoint API

| Method | Endpoint | Akses | Keterangan |
|---|---|---|---|
| POST | `/api/login` | Publik | Autentikasi, balikin token sesi |
| GET | `/api/devices-latest` | Publik | Status & telemetri terbaru semua lampu |
| GET | `/api/telemetry-history` | Publik | Riwayat telemetri satu lampu |
| GET | `/api/system-overview` | Publik | Agregat sistem untuk halaman Dashboard |
| GET | `/api/sector-schedules` | Publik | Jadwal RTC semua sektor |
| PUT | `/api/sector-schedules` | Admin | Simpan jadwal sektor + push MQTT |
| POST | `/api/lights/{id}/command` | Admin | Kendali cepat (dim) |
| GET | `/api/alerts-history` | Publik | Riwayat peringatan |
| PATCH | `/api/alerts/{id}/read` | Publik | Tandai satu peringatan dibaca |
| POST | `/api/alerts/mark-all-read` | Publik | Tandai semua dibaca |
| DELETE | `/api/alerts/{id}` / `/api/alerts` | Admin | Hapus satu / semua peringatan |
| POST | `/api/chat` | Publik | Chat AI (streaming, tool-calling) |
| POST | `/api/chat/analyze-device` | Publik | Analisis AI satu lampu |
| POST | `/api/chat/analyze-system` | Publik | Analisis AI seluruh sistem |
| WS | `/ws/telemetry` | Publik | Broadcast real-time ke dashboard |
| GET | `/health` | Publik | Status server & koneksi database |

Endpoint yang mengubah data (kendali, jadwal, hapus peringatan) memvalidasi peran admin lewat header `X-ACW-Token`, bukan sekadar disembunyikan di UI.

---

## 📡 Alur Data Real-Time

1. ESP32 publish telemetri ke topic MQTT `iot/lights/{device_id}/telemetry`.
2. `mqtt_ingest.py` menyimpannya ke PostgreSQL, mengevaluasi status kesehatan & threshold peringatan, lalu broadcast ke semua dashboard yang terhubung lewat WebSocket.
3. Perangkat dengan `device_id` yang belum terdaftar di tabel `devices` **ditolak** (bukan auto-register) dan memicu peringatan kritis "Perangkat Tidak Terdaftar".
4. Frontend menerima update lewat WebSocket dan menyinkronkan kartu status, peta, grafik, serta badge peringatan tanpa perlu refresh halaman.
