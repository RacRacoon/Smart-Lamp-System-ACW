# 10. Catatan perubahan

Perubahan sejak commit `487f357` ("Perbarui README: firmware, jembatan, dan
arah balik perintah"). Semuanya masih berada di working tree dan belum
di-commit saat dokumen ini ditulis.

```text
 Dashboard_Monitoring/index.html        61 +-
 Dashboard_Monitoring/script.js        255 ++-
 Dashboard_Monitoring/style.css         93 +-
 README.md                              69 +-
 firmware/Core/Src/main.c              883 ++++++++-
 firmware/Core/Src/stm32f1xx_it.c       21 +-
 python-backend/config.py               39 +-
 python-backend/db.py                   58 +
 python-backend/main.py                 59 +-
 python-backend/mqtt_ingest.py         184 ++-
 python-backend/routes_command.py       34 +-
 python-backend/routes_devices.py        6 +
 python-backend/routes_provisioning.py  67 +
 python-backend/schema.sql              11 +
 python-backend/schema_indexes.sql       8 +
 run-dashboard-windows.bat              31 +-
 16 berkas, 1.819 baris masuk, 60 baris keluar
```

Berkas yang belum terlacak git: `cek-sistem-windows.bat`,
`python-backend/tools/cek_nema.py`, `docs/`, dan `document/`.

## 10.1 Kendali dua arah

Dashboard sebelumnya hanya bisa mengatur kecerahan. Sekarang relai dan mode
otomatis LDR ikut bisa dikendalikan, dan posisi saklarnya bertahan melewati
reload halaman.

- `routes_command.py` menerima `relay` dan `auto`, masing-masing opsional,
  minimal satu harus ada. `dim` tidak lagi punya nilai bawaan 0, yang dulu
  membuat perintah "ubah mode otomatis" ikut memadamkan lampu.
- `mqtt_ingest.py` mengurai dan menyimpan `relay` dan `auto` dari telemetri,
  lalu ikut menyiarkannya lewat WebSocket.
- `db.py` mendapat `save_reported_state()`, `update_device_sector()`, dan
  `get_all_device_ids()`.
- `schema.sql` mendapat kolom `relay_on` dan `auto_mode`, keduanya lewat
  `ALTER TABLE ... IF NOT EXISTS` sehingga database yang sudah berisi data bisa
  dimigrasikan tanpa kehilangan apa pun.
- `script.js` mendapat `renderRelayToggle()`, `sendRelay()`,
  `renderAutoToggle()`, dan `sendAutoMode()`.

## 10.2 Pemindahan lampu antar sektor

Sebelumnya lampu yang salah sektor harus dihapus lalu didaftarkan ulang, dan
riwayat telemetrinya ikut hilang karena `ON DELETE CASCADE`.

- `PATCH /api/devices/{device_id}` di `routes_provisioning.py`, admin-only.
  Diuji: 200 untuk pemindahan berhasil, 400 untuk sektor yang tidak ada, 404
  untuk lampu yang belum terdaftar, 403 tanpa token.
- Formulir "Pindahkan Lampu ke Sektor Lain" di halaman Kelola Lampu, dengan
  `handleMoveDevice()` dan `renderMoveDeviceCurrent()`.
- Dropdown `move-device-id` dan `move-device-sector` didaftarkan ke
  `addSectorOptionEverywhere()`, `removeSectorEverywhere()`, dan
  `initCustomSelect()`, sehingga sektor baru langsung muncul tanpa reload.

Diuji langsung pada sistem yang berjalan: `NEMA-01` dipindah dari Sektor
Testing ke Sektor 2 (Kertajaya, Depan ITS), dan halaman Riwayat Data ikut
berubah.

## 10.3 Ketahanan sambungan MQTT

- `mqtt_ingest.start()` memakai `connect_async()` dengan
  `reconnect_delay_set(min_delay=1, max_delay=60)` dan `loop_start()`. Broker
  yang mati tidak lagi menjatuhkan backend saat startup.
- `publish_control_command()` memeriksa `info.rc` dan melempar `RuntimeError`.
  `routes_command.py` menangkapnya dan menjawab 503, bukan 200 atas perintah
  yang tidak pernah berangkat.
- `_clear_retained_command()` dan `_clear_orphan_retained_commands()` membatasi
  umur perintah retained.
- `main.py` menolak start kalau `127.0.0.1:8000` sudah dipakai.
- `/health` bertambah field `broker` dan `ai`.
- `config.MQTT_HOST` bawaannya pindah ke `broker.hivemq.com`.

## 10.4 Perubahan firmware

- `MQTT_BROKER_IP "18.153.87.221"` diganti `MQTT_BROKER_HOST
  "broker.hivemq.com"` di empat tempat.
- `AT+QMTSUB` naik dari QoS 0 ke QoS 1, ditambah `AT+QMTCFG="session",0,1`
  sebagai langkah keempat di rantai konfigurasi.
- `MQTT_AUTO_MIN_MS` dan `MQTT_AUTO_DELTA` mempercepat telemetri selama
  kecerahan otomatis bergerak, lewat `mq_last_pub` dan `mq_pub_level`.

Build bersih setelah perubahan: 55.180 byte flash (42,43 %) dan 4.808 byte RAM
(23,48 %).

## 10.5 Indikator jangkauan board

`renderLinkStatus()` di `script.js`, dengan `LINK_WARN_MS` 2,5 menit dan
`LINK_DOWN_MS` 5 menit, tick tiap 5 detik. Penandanya muncul di panel Kendali
Cepat lewat elemen `link-status-text` di `index.html`.

## 10.6 Revisi sidebar

Lebar sidebar turun dari 300 px ke 232 px. Rinciannya ada di subbab 6.5.

## 10.7 Alat diagnosis baru

- `cek-sistem-windows.bat` memeriksa PostgreSQL, backend dan PID-nya, jumlah
  pendengar port, broker yang dipakai, kunci AI, dan server dashboard.
- `python-backend/tools/cek_nema.py` menguji kedua arah lewat broker dengan
  perintah no-op.

## 10.8 Dokumentasi

- `docs/Laporan-Teknis-NEMA.pdf`, 13 halaman A4, dibuat dari
  `docs/laporan-nema.html` lewat Chrome headless. Teks hitam putih, gambar
  tetap berwarna karena warnanya membawa keterangan: marker merah, toggle
  hijau, dan garis grafik yang dibedakan hanya oleh warna.
- `document/`, dokumentasi ini.

## 10.9 Dua role dan penggantian password

- Kolom `role` di tabel `users` dibatasi `users_role_check` ke `admin` dan
  `user`. Akun `user` hanya membaca, plus menandai peringatan terbaca.
- Seluruh endpoint yang mengubah keadaan memeriksa role di sisi server, bukan
  hanya menyembunyikan tombolnya di dashboard.
- `POST /api/change-password` di `routes_auth.py` mengganti password akun
  pemilik token. Endpoint ini tidak menerima field `username`, tetap meminta
  password lama, dibatasi 10 permintaan per 300 detik per alamat IP, dan
  mencabut sesi lain milik akun yang sama lewat
  `auth.invalidate_user_sessions()`.
- Halaman Pengaturan Akun di dashboard memuat identitas akun dan formulir
  ganti password, terbuka untuk kedua role.
- `python-backend/tools/ganti_password.py` membuat akun baru dan mengganti
  password dari baris perintah, dengan `getpass` supaya nilainya tidak masuk
  riwayat shell.
- `tests/test_change_password.py`, 8 tes, menutup jalur token kosong, password
  lama salah, password baru terlalu pendek, pencabutan sesi, dan rate limit.
