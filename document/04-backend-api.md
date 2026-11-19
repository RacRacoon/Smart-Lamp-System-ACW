# 4. Backend

Satu proses FastAPI menggantikan seluruh `node-red-flow-acw.json` yang dipakai
sebelumnya: REST API, WebSocket, ingest MQTT, penulisan PostgreSQL, dan
evaluasi peringatan.

Jalankan: `uvicorn main:app --host 0.0.0.0 --port 8000`
Dokumentasi otomatis: `http://localhost:8000/docs`

![Swagger UI di `http://localhost:8000/docs`. FastAPI membangun halaman ini dari signature dan model Pydantic tiap route, jadi daftarnya selalu ikut kode. Dua puluh satu endpoint terbagi dalam tag default, devices, alerts, auth, command, chat, schedules, overview, dan provisioning.](gambar/13-swagger.png)

## 4.1 Modul

| Berkas | Isi |
|---|---|
| `main.py` | Entrypoint, CORS, header keamanan, `/health`, `/ws/telemetry`, startup |
| `config.py` | Seluruh tetapan, semuanya bisa ditimpa lewat environment variable |
| `db.py` | Semua kueri SQL dan connection pool |
| `mqtt_ingest.py` | Subscribe telemetri, validasi, broadcast, publisher perintah |
| `alerts.py` | Klasifikasi kesehatan dan aturan peringatan |
| `auth.py` | Hash password argon2id, sesi, pencatat kegagalan login |
| `rate_limit.py` | Rate limit per kategori |
| `ws_manager.py` | Daftar klien WebSocket dan broadcast lintas thread |
| `ai_chat.py` | Klien HTTP ke endpoint OpenAI-compatible |
| `routes_*.py` | Endpoint REST per bidang |

## 4.2 Autentikasi

`POST /api/login` menukar username dan password dengan token sesi:

```json
{"role": "admin", "token": "tok_..."}
```

Token dikirim kembali di header `X-ACW-Token`. Sesi hidup
`SESSION_DURATION_HOURS` (12 jam) dan disimpan di memori proses, jadi restart
backend mencabut semua sesi.

Password di-hash dengan argon2id. Hash scrypt lama dari era Node-RED masih bisa
diverifikasi dan di-upgrade diam-diam ke argon2id saat login berhasil.

Waktu respons login dibuat konsisten supaya username yang valid tidak bisa
ditebak dari selisih waktu jawaban. Kegagalan berturut-turut kelipatan tiga
memicu peringatan `Percobaan Login Gagal Berulang`.

### Penggantian password

`POST /api/change-password` mengubah password akun pemilik token, dan hanya itu.
Endpoint ini tidak menerima field `username`. Kalau menerimanya, siapa pun yang
menguasai satu token bisa menimpa password akun lain tanpa tahu password
lamanya.

Password lama tetap wajib disertakan walau tokennya sudah sah. Token
membuktikan sesi masih hidup, bukan bahwa yang sedang memegang laptop itu
pemilik akunnya.

Permintaannya dibatasi per alamat IP dengan parameter yang sama dengan login,
10 per 300 detik. Pembatas di `/api/login` tidak menutupi pintu ini, dan tanpa
pembatas sendiri password lama bisa ditebak dari sini secepat jaringan
mengizinkan.

Sesudah berhasil, semua sesi lain milik akun itu dicabut lewat
`auth.invalidate_user_sessions()`. Sesi yang dipakai penggantinya sendiri
dikecualikan supaya dia tidak ikut terlempar ke layar login. Jumlah yang dicabut
dikembalikan sebagai `sessions_revoked`.

Dua peran: `admin` dan `user`. Dashboard menampilkan yang kedua sebagai
"Petugas Monitoring". Peran itu tidak bisa mengirim perintah, membuat sektor, mendaftarkan lampu, memindahkannya, atau menghapus
sektor.

## 4.3 Daftar endpoint

Semua berprefiks `/api` kecuali `/health` dan `/ws/telemetry`.

### Umum

| Metode | Path | Akses | Isi |
|---|---|---|---|
| `GET` | `/health` | Terbuka | Status db, mqtt, broker, dan kunci AI |
| `WS` | `/ws/telemetry` | Terbuka | Broadcast telemetri dan peringatan |

### Autentikasi

| Metode | Path | Akses | Isi |
|---|---|---|---|
| `POST` | `/api/login` | Terbuka | Body `{username, password}`, balasan `{role, token}` |
| `POST` | `/api/logout` | Token | Mencabut sesi di sisi server |

### Perangkat dan telemetri

| Metode | Path | Akses | Isi |
|---|---|---|---|
| `GET` | `/api/devices-latest` | Terbuka | Pembacaan terakhir tiap lampu, termasuk `relay_on` dan `auto_mode` |
| `GET` | `/api/telemetry-history` | Terbuka | Query `device_id`, deret riwayat untuk grafik |
| `GET` | `/api/system-overview` | Terbuka | Agregat seluruh sistem untuk halaman Dashboard |

### Kendali

| Metode | Path | Akses | Isi |
|---|---|---|---|
| `POST` | `/api/lights/{device_id}/command` | Admin | Body `{relay?, dim?, auto?}`, minimal satu |

Balasan 503 berarti backend tidak bisa publish ke broker.
`publish_control_command()` memeriksa `info.rc` dari paho-mqtt dan melempar
`RuntimeError` kalau penerbitan gagal, alih-alih menjawab 200 atas perintah
yang tidak pernah berangkat.

### Sektor dan pendaftaran lampu

| Metode | Path | Akses | Isi |
|---|---|---|---|
| `GET` | `/api/sectors` | Terbuka | Daftar nama sektor |
| `POST` | `/api/sectors` | Admin | Body `{sector_name}` |
| `POST` | `/api/devices` | Admin | Body `{device_id, sector_name, lat?, lng?, max_lifespan?}` |
| `PATCH` | `/api/devices/{device_id}` | Admin | Body `{sector_name}`, memindahkan lampu antar sektor |
| `DELETE` | `/api/sectors/{sector_name}` | Admin + password | Body `{username, password}` |

Penghapusan sektor memakai step-up auth. Sesi admin yang masih hidup tidak
cukup: penghapus harus membuktikan tahu password admin saat itu juga, karena
laptop admin yang ketinggalan terbuka bukan berarti siapa pun boleh menghapus
sektor.

`PATCH /api/devices/{device_id}` menjawab 400 kalau sektor tujuan tidak ada,
404 kalau lampunya belum terdaftar, dan 403 tanpa token admin.

### Jadwal

| Metode | Path | Akses | Isi |
|---|---|---|---|
| `GET` | `/api/sector-schedules` | Terbuka | Peta nama sektor ke daftar fase |
| `PUT` | `/api/sector-schedules` | Admin | Mengganti seluruh fase satu sektor |

Tiap fase membawa `schedule_time`, `dim_level` (1 sampai 10), dan `cct_level`
(0 sampai 100).

### Peringatan

| Metode | Path | Akses | Isi |
|---|---|---|---|
| `GET` | `/api/alerts-history` | Terbuka | Query `limit`, 1 sampai 500, bawaan 50 |
| `PATCH` | `/api/alerts/{alert_id}/read` | Terbuka | Menandai satu peringatan terbaca |
| `POST` | `/api/alerts/mark-all-read` | Terbuka | Menandai semuanya terbaca |
| `DELETE` | `/api/alerts/{alert_id}` | Admin | Menghapus satu peringatan |
| `DELETE` | `/api/alerts` | Admin | Mengosongkan kotak peringatan |

### Asisten AI

| Metode | Path | Akses | Isi |
|---|---|---|---|
| `POST` | `/api/chat/analyze-system` | Terbuka | Ringkasan status seluruh sistem |
| `POST` | `/api/chat/analyze-device` | Terbuka | Analisis satu lampu |
| `POST` | `/api/chat` | Terbuka | Percakapan, balasan streaming |

Tanpa `GEMINI_API_KEY`, ketiganya menjawab 503 dan sisa dashboard tetap
berjalan normal.

## 4.4 Endpoint `/health`

```json
{"status":"ok","db":"ok","mqtt":"ok",
 "broker":"broker.hivemq.com:1883","ai":"tanpa kunci"}
```

Status keseluruhan jadi 503 kalau database atau MQTT gagal. Kunci AI sengaja
tidak ikut menentukan: asisten AI itu fitur tambahan, dan menjadikan backend
"degraded" karena ketiadaannya akan menenggelamkan tanda bahaya yang sungguhan.
Endpoint ini juga tidak pernah menampilkan kunci AI, sebagian pun.

Field `broker` menyebut host dan port yang sedang dipakai. Field itu ada karena
satu gangguan yang menghabiskan berjam-jam: dua backend berjalan bersamaan,
masing-masing tersambung ke broker berbeda, dan tidak ada cara melihatnya dari
luar.

## 4.5 WebSocket

`/ws/telemetry` hanya broadcast. Dashboard tidak mengirim apa pun; loop
`receive_text()` di sisi server ada untuk mendeteksi putusnya sambungan.

Tiga bentuk pesan dikirim:

**Telemetri.** Membawa `id`, `device_id`, `sector`, `health`, `uptime`, `volt`,
`current`, `power`, `dim`, dan secara opsional `relay`, `auto`, `lat`, `lng`.
Kunci opsional dihilangkan kalau board tidak melaporkannya, sehingga dashboard
bisa membedakan "tidak dilaporkan" dari "mati". Tanpa itu, marker peta akan
digambar di koordinat nol dan toggle akan tampil mati untuk lampu yang sedang
menyala.

**Peringatan perangkat terdaftar.** Membawa `id`, `alert: true`, `alertType`,
`level`, `title`, `message`, dan angka pembacaannya.

**Peringatan perangkat tak terdaftar.** Membawa `device_id` tetapi sengaja
tidak membawa `id`. Kunci `id` memicu dashboard mendaftarkan node baru secara
otomatis, dan perangkat asing harus muncul di Kotak Peringatan tanpa pernah
jadi node yang bisa dikendalikan atau ditampilkan di peta.

## 4.6 Rate limit

| Kategori | Batas | Jendela | Kunci |
|---|---|---|---|
| `login` | 10 | 300 detik | Alamat IP |
| `public` | 60 | 10 detik | Alamat IP |
| `admin_write` | 30 | 10 detik | Token sesi |
| `ai` | 20 | 60 detik | Alamat IP |

Batas AI perlu diturunkan kalau penyedianya diganti ke Groq, yang membatasi
8.000 token per menit.

## 4.7 Pencegahan backend ganda

`_port_sudah_dipakai()` menolak start kalau sudah ada yang mendengar di
`127.0.0.1:8000`, dan prosesnya keluar dengan kode 1.

Pemeriksaan ini menutup perilaku khusus Windows. Bawaan `API_HOST` adalah
`0.0.0.0`, dan Windows mengizinkan `0.0.0.0:8000` hidup berdampingan dengan
`127.0.0.1:8000` milik proses lain. Uvicorn tidak gagal, melainkan menyala
tanpa keluhan, sementara alamat `127.0.0.1` yang lebih spesifik membuat semua
permintaan "localhost" mendarat di backend yang satunya. Dua backend, dua
broker, dan perintah dashboard hilang tanpa jejak error di mana pun.

## 4.8 Ketahanan sambungan MQTT

`start()` memakai `connect_async()` dengan `reconnect_delay_set(min_delay=1,
max_delay=60)` lalu `loop_start()`. Versi lama memakai `client.connect()` yang
blocking, sehingga broker yang mati menjatuhkan seluruh backend saat startup:

```text
TimeoutError: timed out
ERROR: Application startup failed. Exiting.
```

Sekarang backend tetap hidup dan melayani REST, `/health` menjawab 503 dengan
`"mqtt": "error"`, dan paho menyambung ulang sendiri saat broker kembali.
