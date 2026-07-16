# Smart Lamp System - City Manager Dashboard

Dashboard Monitoring dan Manajemen Sistem Penerangan Jalan Pintar (Smart Street Lighting) berbasis Web Real-Time. Dashboard ini memvisualisasikan data telemetri lampu jalan secara 3D, memungkinkan kendali manual override, penjadwalan berbasis waktu (RTC), otomatisasi berbasis sensor LDR, serta analisis log historis menggunakan grafik interaktif.

---

## 🚀 Fitur Utama

### 1. **Dasbor Monitoring Real-Time (Overview Perangkat)**
* **Visualisasi Peta 3D**: Menggunakan **Maplibre GL** dan **OpenFreeMap** untuk menampilkan posisi tiang lampu jalan secara real-time dengan detail status interaktif pada split-panel.
* **Status Kesehatan Perangkat**: Indikator status dinamis (*Healthy*, *Warning*, *Critical*) berdasarkan kondisi lampu.
* **Perhitungan Lifespan**: Estimasi sisa umur operasional lampu (misal: 4,500 / 10,000 jam) dengan visualisasi bar kemajuan dinamis.
* **Monitoring Daya Aktif (PZEM)**: Menampilkan data Tegangan (V), Arus (A), dan Daya Aktif (W) secara langsung dari perangkat ESP32.
* **Kendali Cepat (Manual Override)**: Fitur penguncian keamanan dan slider manual untuk mengatur tingkat redup (*Dimming* 1-10V) serta kehangatan warna (*CCT* 0-100%).

### 2. **Manajemen Node & Sektor (Manage Nodes)**
* **Konfigurasi Fleksibel**: Pilihan konfigurasi per-node individu maupun konfigurasi massal per-sektor (contoh: Sektor 1 Jalan Tunjungan, Sektor 2 Kertajaya).
* **Otomatisasi LDR**: Pengaturan sensor cahaya (LDR) otomatis yang memutus daya lampu (0%) secara mandiri pada siang hari.
* **Penjadwalan 3 Fase (RTC)**: Integrasi dengan modul RTC DS3231 untuk jadwal otomatisasi waktu:
  * **Fase 1 (Sore)**: Mulai operasi/dimming sore hari.
  * **Fase 2 (Tengah Malam)**: Mode hemat energi/redup maksimal.
  * **Fase 3 (Dini Hari)**: Antisipasi kabut dengan cahaya hangat/CCT tinggi.
* **Integrasi MQTT**: Tombol kirim konfigurasi terintegrasi langsung dengan broker MQTT melalui backend Node-RED.

### 3. **Log Telemetri & Data Historis (Telemetry Logs)**
* **Filter Perangkat**: Memilih data historis per-tiang lampu.
* **Metrik Kumulatif**: Rata-rata Tegangan, Rata-rata Arus, dan Konsumsi Daya Kumulatif.
* **Grafik Interaktif**: Menggunakan **Chart.js** untuk memplot fluktuasi tegangan, arus, dan watt secara berkala.

---

## 🛠️ Teknologi yang Digunakan

* **Frontend**: HTML5, Vanilla CSS3 (Custom Dark Theme & Responsive Layout), JavaScript (ES6)
* **Visualisasi & Peta**: Maplibre GL, OpenFreeMap (Vektor 3D)
* **Grafik**: Chart.js
* **Komunikasi Backend & Real-Time**: Node-RED, WebSockets (`ws://localhost:1880`), REST API (`http://localhost:1880/api`)
* **Basis Data**: PostgreSQL (melalui integrasi Node-RED)
* **Protokol IoT**: MQTT (untuk kontrol dan pengiriman parameter ke ESP32)

---

## 📂 Struktur Repositori

```bash
Dashboard_Monitoring/
├── index.html   # Struktur utama halaman (Dashboard, Manage, & Telemetry)
├── style.css    # Gaya UI, tema gelap, transisi panel, dan tata letak responsif
├── script.js    # Logika WebSocket, Chart.js, Maplibre GL, serta sinkronisasi state
└── README.md    # Dokumentasi proyek
```

---

## ⚙️ Persiapan & Jalankan Lokal

### 1. Prasyarat (Prerequisites)
Pastikan Anda sudah menginstal dan menjalankan:
1. **Node-RED**: Berjalan pada port default (`http://localhost:1880`).
2. **PostgreSQL**: Database dengan tabel telemetri dan konfigurasi lampu.
3. **MQTT Broker**: (Misalnya Mosquitto) untuk lalu lintas data sensor ESP32 dan pengiriman konfigurasi.

### 2. Konfigurasi Endpoint Backend
Jika Node-RED atau database Anda berjalan di IP/port yang berbeda, sesuaikan URL pada bagian awal file `script.js`:
```javascript
// Sesuaikan dengan alamat server Node-RED Anda
const NODE_RED_WS_URL = "ws://localhost:1880/ws/telemetry";
```

### 3. Menjalankan Dashboard
Karena dashboard menggunakan vanilla HTML/JS, Anda dapat membukanya secara langsung atau menggunakan local server sederhana:

**Menggunakan VS Code Live Server (Direkomendasikan)**:
1. Buka folder `Dashboard_Monitoring` di VS Code.
2. Klik kanan pada `index.html` dan pilih **Open with Live Server**.

**Menggunakan Python HTTP Server**:
Jalankan perintah ini di dalam folder proyek melalui terminal:
```bash
python3 -m http.server 8000
```
Buka browser dan akses ke `http://localhost:8000`.

---

## 📡 Skema Integrasi Data Node-RED
Aplikasi ini dirancang untuk bekerja secara dinamis. Alur data yang didukung oleh `script.js`:
1. **Inisialisasi Awal**: Saat halaman dimuat, web melakukan `fetch` ke API Node-RED (`/api/devices-latest`) untuk mendapatkan koordinat dan data telemetri terbaru yang disimpan di PostgreSQL.
2. **Dinamis Node Detection**: Jika ada perangkat baru terhubung (misal: `L-107`) yang belum didefinisikan secara lokal, frontend akan otomatis menambahkannya ke dropdown pilihan, membuat pin peta baru, dan mendaftarkan konfigurasi defaultnya.
3. **Koneksi WebSocket**: Menjaga koneksi real-time untuk memperbarui status daya PZEM, tingkat lifespan, koordinat, dan peringatan tanpa perlu me-refresh halaman.