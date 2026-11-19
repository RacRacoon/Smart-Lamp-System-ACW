# 9. Keamanan

## 9.1 Celah yang sudah ditutup

| Masalah | Perbaikan |
|---|---|
| XSS tersimpan lewat `device_id` perangkat asing | `escapeHtml()` dan `escapeJsString()` di setiap perenderan pesan peringatan |
| Timing side-channel di login | Waktu respons dibuat konsisten, username valid tidak bisa ditebak dari selisih waktu |
| Penyuntikan wildcard ke nama topik MQTT | `device_id` divalidasi `^[A-Za-z0-9._-]{1,64}$` sebelum dipakai menyusun topik |
| Perangkat palsu menyusup ke data | `device_id` yang belum terdaftar ditolak total, datanya tidak disimpan |
| Hash password lemah | argon2id, hash scrypt lama di-upgrade diam-diam saat login berhasil |
| Logout yang hanya membersihkan browser | `invalidate_session()` mencabut token di sisi server |
| Batas alert yang tak terbatas | `limit` di-clamp 1 sampai 500 |
| DoS lewat kehabisan koneksi pool | Pool 2 sampai 25 koneksi, dilepas kembali di `finally` |
| Penghapusan sektor dengan sesi yang ketinggalan terbuka | Step-up auth: username dan password harus diketik ulang saat itu juga |
| Permintaan bertubi-tubi | Empat kategori rate limit, lihat subbab 4.6 |

Header keamanan dipasang dari dua tempat: `Caddyfile` di repo, dan middleware
di `main.py`. Caddy hanya aktif kalau backend memang berjalan di belakangnya,
sedangkan port 8000 sering diakses langsung. Browser memakai yang pertama
sampai, dan tumpang tindihnya tidak merugikan.

## 9.2 Celah yang masih terbuka

### Broker publik tanpa autentikasi

`broker.hivemq.com` tidak meminta kredensial. Siapa pun yang tahu nama
topiknya bisa membaca telemetri dan publish perintah ke
`iot/lights/NEMA-01/command`, yang berarti mengendalikan relai jala listrik.

Kondisi ini cukup untuk purwarupa. Sebelum pemasangan di lapangan, broker harus diganti dengan
yang punya kredensial sendiri, dan topiknya dibatasi per perangkat lewat ACL.
Board sudah memakai TLS di port 8883, jadi yang kurang tinggal autentikasinya.

### Kredensial di dalam repo

Repo `RacRacoon/Smart-Lamp-System-ACW` bersifat publik, dan dua password ada
di dalamnya sebagai teks biasa:

| Nilai | Letaknya |
|---|---|
| Password akun dashboard `admin` | `README.md` bagian 5.3, sebagai argumen `auth.hash_password()` |
| Password PostgreSQL | `python-backend/config.py` baris 55, bawaan `DB_PASSWORD` |

Password akun dashboard di mesin pengembangan ini sudah diganti dari nilai
tersebut, tetapi penggantian itu tidak menutup celahnya: `README.md`,
`python-backend/config.py`, dan seluruh riwayat git tetap memuat nilai lama
sebagai teks biasa, dan password PostgreSQL masih memakai nilai itu.

Keduanya harus diganti dan dipindah ke environment variable sebelum sistem ini
dipasang di luar mesin pengembangan.

### Kunci API AI

Jangan tulis `GEMINI_API_KEY` ke dalam `run-dashboard-windows.bat` atau berkas
lain yang masuk git. Pasang lewat `setx GEMINI_API_KEY "..."`.

### CORS terbuka

`CORS_ALLOW_ORIGINS` bawaannya `*`. Batasi ke asal dashboard yang sebenarnya
saat sistem dipasang.

## 9.3 Syarat sebelum pemasangan di lapangan

Lima hal berikut harus selesai sebelum unit ini mengendalikan lampu jalan di
lapangan:

1. Broker sendiri dengan kredensial dan ACL per perangkat.
2. Kredensial dashboard dan database diganti, disimpan di luar repo.
3. CORS dibatasi.
4. Sertifikat broker diverifikasi di sisi board, bukan hanya TLS yang menyala.
5. Mekanisme pembaruan firmware jarak jauh, karena `MQTT_BROKER_HOST` dan
   `MQTT_CLIENT_ID` masih dikompilasi ke dalam `main.c`.
