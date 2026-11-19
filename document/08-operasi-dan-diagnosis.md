# 8. Operasi dan diagnosis

## 8.1 Alat pemeriksaan

### `cek-sistem-windows.bat`

Memeriksa tumpukan yang sedang berjalan di PC, dari luar:

1. Layanan PostgreSQL hidup.
2. Ada yang mendengar di port 8000, dan menyebut PID-nya.
3. Backend menjawab `/health`, dengan status db, mqtt, kunci AI, dan nama
   broker yang sedang dipakai.
4. Jumlah pendengar di port backend. Lebih dari satu berarti dua backend
   berjalan bersamaan.
5. Server halaman dashboard di port 5500.

### `python-backend/tools/cek_nema.py`

Menguji kedua arah lewat broker, bukan lewat backend:

```bash
python tools/cek_nema.py
python tools/cek_nema.py --device NEMA-01
python tools/cek_nema.py --broker broker.hivemq.com --timeout 90
```

Langkah pertama menunggu telemetri berikutnya datang, yang membuktikan arah
naik hidup. Langkah kedua mengirim perintah berisi status relai board saat
ini, dibaca dari telemetri langkah pertama, sehingga perintah itu sampai,
diterapkan, dan tidak mengubah apa pun. Lampu tidak berkedip. Board selalu
melapor segera setelah menerima perintah yang dipahaminya, dan kedatangan
laporan itulah yang membuktikan arah turun hidup.

Langkah ketiga memeriksa apakah ada perintah retained yang masih menggantung di
broker.

## 8.2 Gangguan yang pernah terjadi

Enam gangguan berikut terjadi selama pengembangan, dan tidak satu pun
memunculkan pesan error.

### Dua backend berjalan bersamaan

**Gejala.** Tombol di dashboard menjawab 200, board tidak pernah bergerak.

**Sebab.** Windows mengizinkan `0.0.0.0:8000` hidup berdampingan dengan
`127.0.0.1:8000` milik proses lain. Permintaan ke `localhost` mendarat di
backend yang `127.0.0.1`, yang kebetulan tersambung ke `broker.emqx.io`.
Perintah dashboard di-publish ke broker publik yang sama sekali lain.

**Perbaikan.** `_port_sudah_dipakai()` menolak start kedua, `/health` menyebut
nama broker, dan `cek-sistem-windows.bat` menghitung jumlah pendengar port.

### Subscribe QoS 0 di board

**Gejala.** Perintah hilang sesekali, tanpa pola yang jelas.

**Sebab.** `AT+QMTSUB` memakai QoS 0, sehingga perintah yang tiba saat radio
tersendat hilang tanpa jejak.

**Perbaikan.** QoS 1 pada subscribe, ditambah `AT+QMTCFG="session",0,1`.

### `client.connect()` memblokir startup

**Gejala.** Backend menolak hidup:

```text
TimeoutError: timed out
ERROR: Application startup failed. Exiting.
```

**Sebab.** Broker yang mati menjatuhkan seluruh proses, bukan hanya fitur
MQTT-nya.

**Perbaikan.** `connect_async()` dengan `reconnect_delay_set()` dan
`loop_start()`.

### Alamat IP broker tertanam di firmware

**Gejala.** Board berhenti melapor sama sekali pada 21 Oktober 2026.

**Sebab.** `18.153.87.221` adalah satu node publik HiveMQ. Node itu
berhenti menjawab, sementara `broker.hivemq.com` menunjuk ke node sehat lain
(`52.28.81.2`, `54.93.55.163`).

**Perbaikan.** Nama domain di firmware, bukan IP.

### Perintah retained yang tertinggal

**Gejala.** Lampu padam sendiri tiap kali board menyambung ulang, berhari-hari
setelah tombolnya ditekan.

**Sebab.** `{"relay":"off"}` tertinggal di broker sebagai retained message.
Timer TTL yang seharusnya menghapusnya mati bersama proses backend.

**Perbaikan.** `_clear_orphan_retained_commands()` dipanggil dari
`_on_connect()`, menyapu sisa perintah tiap kali backend menyambung.

### Ambang data usang 15 menit

**Gejala.** Board yang sudah padam sepuluh menit masih tampil sehat di layar.

**Sebab.** Ambang 15 menit terhadap laporan tiap 60 detik.

**Perbaikan.** Indikator jangkauan board di panel Kendali Cepat dengan ambang
2,5 menit dan 5 menit.

## 8.3 Alur diagnosis

Ikuti urutan ini untuk menemukan bagian yang bermasalah sebelum mengubah apa pun:

1. **`cek-sistem-windows.bat`.** Kalau backend tidak menjawab atau brokernya
   salah, berhenti di sini. Jangan periksa board.
2. **`python tools/cek_nema.py`.** Skrip ini berkomunikasi langsung dengan broker,
   tanpa melewati backend. Hasilnya memisahkan "board diam" dari "backend salah alamat".
3. **Konsol UART board.** Perintah `pub` menyebut state machine MQTT saat itu, dan `s`
   mencetak status lengkap. LED heartbeat di PB8 berkedip selama loop utama
   berjalan.

Angka terbaru di dashboard hanya membuktikan arah naik hidup. Kalau perintah
tidak sampai, periksa arah turun dengan `cek_nema.py`.

## 8.4 Nilai acuan pengukuran

| Yang diukur | Nilai |
|---|---|
| Waktu tanggap perintah saat sambungan sehat | 0,7 sampai 0,8 detik |
| Jeda telemetri normal | 60 detik |
| Jeda telemetri saat kecerahan auto bergerak | 10,1 / 9,9 / 10,4 detik |
| Jeda setelah kecerahan tenang kembali | 68,7 detik |
| Padam teramati, pulih sendiri | 4,5 menit dan lebih dari 10 menit |
| Pemakaian flash firmware | 55.180 byte dari 127 KB, 42,43 % |
| Pemakaian RAM firmware | 4.808 byte dari 20 KB, 23,48 % |
| Perkiraan kuota telemetri | sekitar 12 MB per bulan |

## 8.5 Masalah teknis yang belum selesai

| Butir | Keterangan |
|---|---|
| Broker publik tanpa autentikasi | Siapa pun yang tahu nama topik bisa mengendalikan relai jala listrik |
| GPS berbagi kanal dengan konsol | `MODEM_BRINGUP 1` mematikan GPS; diagnostiknya perlu dipindahkan ke payload telemetri |
| Kapasitor curah dekat modem | 470 sampai 1000 µF, dan verifikasi catu 2 A, belum dikerjakan |
| Kestabilan sambungan seluler | Padam beberapa menit masih terjadi dan pulih sendiri |
