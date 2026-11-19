# 5. Database

PostgreSQL. Bentuk tabel ada di `python-backend/schema.sql`, indeks tambahan di
`schema_indexes.sql`. Keduanya aman dijalankan ulang: setiap kolom baru
ditambahkan lewat `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`.

Nama database `smart_lights`, pengguna `admin`, port 5432.

## 5.1 Tabel `users`

| Kolom | Tipe | Catatan |
|---|---|---|
| `id` | SERIAL | |
| `username` | VARCHAR(50) | |
| `password_hash` | TEXT | argon2id. Hash scrypt lama dari era Node-RED masih diverifikasi dan di-upgrade saat login berhasil |
| `role` | VARCHAR(20) | `admin` atau `user`, dijaga CHECK constraint `users_role_check` |
| `created_at` | TIMESTAMP | |

## 5.2 Tabel `sectors`

| Kolom | Tipe | Catatan |
|---|---|---|
| `sector_name` | VARCHAR(100) PK | |
| `ldr_mode` | BOOLEAN | `true` berarti kecerahan sektor ini mengikuti LDR fisik, bukan jadwal RTC |
| `updated_at` | TIMESTAMP | |

## 5.3 Tabel `devices`

| Kolom | Tipe | Catatan |
|---|---|---|
| `device_id` | VARCHAR(50) PK | Dibatasi `[A-Za-z0-9._-]{1,64}` di lapisan aplikasi, bukan lewat CHECK constraint |
| `sector_name` | VARCHAR(100) FK | `ON DELETE SET NULL` |
| `latitude`, `longitude` | DOUBLE PRECISION | |
| `max_lifespan` | INTEGER | Jam pakai sebelum status Need Maintenance, bawaan 10000 |
| `lamp_hours` | DOUBLE PRECISION | Usia pakai akumulatif, hanya boleh naik |
| `relay_on` | BOOLEAN | Status terakhir yang dilaporkan board. NULL berarti belum pernah melapor |
| `auto_mode` | BOOLEAN | Idem untuk mode otomatis LDR |
| `lamp_seen` | TIMESTAMP | Telemetri terakhir yang sudah dihitung ke `lamp_hours` |
| `created_at` | TIMESTAMP | |

### Perhitungan `lamp_hours` di backend

Angka ini dulu diambil mentah dari field `uptime` telemetri, yang berarti ia
ikut ter-reset tiap board dinyalakan ulang. Indikator yang menentukan kapan
lampu diganti tidak boleh punya sifat itu. Sekarang `db.accrue_lamp_hours()`
menambahkan selisih waktu antara `lamp_seen` dan telemetri yang baru masuk,
hanya selama lampu menyala.

### Kolom `relay_on` dan `auto_mode`

Sebelum kedua kolom ini ada, dashboard yang baru dimuat ulang tidak punya
sumber apa pun untuk posisi saklarnya, dan semuanya tampil mati apa pun yang
sedang terjadi pada lampu. Keduanya menyimpan apa yang dilaporkan board, bukan
perintah terakhir yang dikirim dashboard. Mode otomatis juga bisa diubah dari
konsol UART board, jadi board yang menjadi sumber kebenarannya.

### Dampak penghapusan sektor

`ON DELETE SET NULL` membuat lampu jadi "tanpa sektor". Admin harus
memindahkan atau menghapus lampunya lebih dulu.

## 5.4 Tabel `telemetry_logs`

| Kolom | Tipe | Catatan |
|---|---|---|
| `id` | BIGSERIAL | Volume baris terbesar di skema ini, INTEGER akan kena batas lebih dulu |
| `device_id` | VARCHAR(50) FK | `ON DELETE CASCADE` |
| `volt` | NUMERIC(5,2) | |
| `current` | NUMERIC(5,3) | |
| `power` | NUMERIC(6,2) | |
| `uptime` | NUMERIC(10,2) | Usia pakai dari `devices.lamp_hours`, bukan uptime board |
| `dim` | INTEGER | Kecerahan saat pembacaan ini diambil |
| `created_at` | TIMESTAMP | |

## 5.5 Tabel `alerts`

| Kolom | Tipe | Catatan |
|---|---|---|
| `id` | SERIAL | |
| `device_id` | VARCHAR(50) FK | `ON DELETE CASCADE`, riwayat ikut terhapus bersama lampunya |
| `level` | VARCHAR(20) | `Critical`, satu-satunya level yang dipakai saat ini |
| `title` | VARCHAR(100) | |
| `message` | TEXT | Bisa memuat `device_id` asing apa adanya |
| `volt`, `current`, `power` | NUMERIC | Pembacaan saat peringatan terpicu |
| `threshold_info` | VARCHAR(100) | Ambang yang dilanggar |
| `is_read` | BOOLEAN | |
| `created_at` | TIMESTAMP | |

Kolom `message` pernah jadi jalur XSS tersimpan. Perangkat asing bisa memilih
`device_id` sendiri, dan nama itu ikut tertulis ke pesan peringatan yang
kemudian dirender di dashboard. Setiap perenderan sekarang melewati
`escapeHtml()` atau `escapeJsString()` di `script.js`.

## 5.6 Tabel `sector_schedules`

| Kolom | Tipe | Catatan |
|---|---|---|
| `id` | SERIAL | |
| `sector_name` | VARCHAR(100) FK | `ON DELETE CASCADE` |
| `schedule_time` | TIME | |
| `dim_level` | INTEGER | 1 sampai 10, divalidasi Pydantic, tanpa CHECK constraint setara di DB |
| `cct_level` | INTEGER | 0 sampai 100, idem |

`UNIQUE (sector_name, schedule_time)` mencegah dua fase pada jam yang sama.

## 5.7 Aturan peringatan

`alerts.evaluate_alert()` memeriksa tiga aturan berurutan dan hanya satu yang
bisa terpicu per pesan.

| Urutan | Syarat | Judul |
|---|---|---|
| 1 | `volt > 240` | Lonjakan Tegangan |
| 2 | `volt < 200` dan tegangannya memang dilaporkan | Tanpa Tegangan Jala (kalau 0 V) atau Perangkat Offline / Tegangan Low |
| 3 | `current > 1.5` | Lonjakan Arus |

Aturan kedua semula mensyaratkan `0 < volt`, sehingga kasus paling jelas, yaitu
lampu terlepas dan jala listrik hilang, justru tidak memicu apa pun.
Pengecualian itu ada alasannya: payload yang tidak membawa field `volt` juga
terbaca sebagai 0. Yang dibedakan sekarang bukan angkanya, melainkan apakah
angkanya memang dilaporkan.

Gangguan yang bertahan dicatat sekali per `ALERT_COOLDOWN_SECONDS` (300 detik),
bukan tiap telemetri.

Dua peringatan lain datang dari luar jalur telemetri:
`Percobaan Login Gagal Berulang` dan `Perangkat Tidak Terdaftar`.

## 5.8 Klasifikasi kesehatan

| Jam pakai | Status |
|---|---|
| Di bawah 8.000 | Healthy |
| 8.000 sampai 9.999 | Warning |
| 10.000 ke atas | Need Maintenance |
