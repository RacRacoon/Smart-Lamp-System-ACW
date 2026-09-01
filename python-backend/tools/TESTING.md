# Tes Sistem Penuh Pakai `simulate_light.py`

Simulator lampu - publish ke topic MQTT yang SAMA persis dengan firmware ESP32 asli,
backend tidak bisa bedakan ini dari lampu sungguhan. Semua skenario di bawah sudah
dites langsung (14 Agu 2026) lawan backend + database hidup, bukan cuma dugaan.

## Persiapan

```bash
cd python-backend
python tools/simulate_light.py --device-id SIM-01 --register \
    --admin-user admin --admin-password <password_asli>
```

`--register` daftarin sektor "Sektor 1 (Simulasi)" (kalau belum ada) + device lewat
API beneran (`routes_provisioning.py`), bukan lewat SQL langsung - jalur validasinya
ikut ketes juga.

## Skenario & Cara Verifikasi

### 1. Telemetry normal
```bash
python tools/simulate_light.py --device-id SIM-01
```
**Cek:** muncul live di peta/kartu dashboard (WebSocket), baris baru masuk
`telemetry_logs` tiap `--interval` detik, kepakai di grafik "Rata-rata Telemetri"
(Dashboard) dan KPI.

### 2. Lonjakan tegangan (>240V)
```bash
python tools/simulate_light.py --device-id SIM-01 --scenario spike --count 1
```
**Cek:** alert "Lonjakan Tegangan" muncul di Kotak Peringatan, level Critical.

### 3. Perangkat offline / tegangan rendah (<200V)
```bash
python tools/simulate_light.py --device-id SIM-01 --scenario offline --count 1
```
**Cek:** alert "Perangkat Offline / Tegangan Low".

### 4. Lonjakan arus (>1.5A)
```bash
python tools/simulate_light.py --device-id SIM-01 --scenario current_spike --count 1
```
**Cek:** alert "Lonjakan Arus".

### 5. Device belum terdaftar
```bash
python tools/simulate_light.py --device-id SIM-GHOST --count 1
# TANPA --register - device_id ini sengaja tidak didaftarkan
```
**Cek:** alert "Perangkat Tidak Terdaftar" muncul (level Critical), TAPI
`telemetry_logs` untuk `SIM-GHOST` tetap kosong - data device asing ditolak total,
cuma alert-nya yang tersimpan.

### 6. device_id charset tidak valid
```bash
python tools/simulate_light.py --device-id "SIM BAD" --count 1
```
**Cek:** backend DIAM TOTAL - nol alert, nol baris DB, cuma satu baris log warning
("bentuk device_id tidak valid"). Ini gerbang `config.is_valid_device_id()` yang
nutup celah XSS tersimpan lama (commit `01e8a3b`) - device_id bermarkup tidak boleh
pernah sampai ke tabel `alerts`/`devices` sama sekali.

### 7. Kendali dim dari dashboard
Jalankan simulator biasa di satu terminal (`--interval 3`, tanpa `--count` biar
tidak langsung berhenti), lalu di terminal lain klik slider **Kendali Cepat** di
dashboard (atau `POST /api/lights/SIM-01/command`).
**Cek:** log simulator nampilin `<< terima command DIM baru: N`, publish
BERIKUTNYA otomatis bawa `dim=N` yang baru - buktikan loop kendali dua arah jalan,
bukan cuma satu arah device->dashboard.

### 8. Jadwal RTC
Simulator jalan seperti di atas, admin simpan jadwal sektor lewat halaman **Kelola
Lampu** (atau `PUT /api/sector-schedules`).
**Cek:** log simulator nampilin `<< terima command JADWAL baru: N fase` - buktikan
`mqtt_ingest.publish_schedule_command()` (retained message) beneran nyampe device.

### 9. Banyak device sekaligus (belum dites otomatis, rencana lanjutan)
```bash
for i in 1 2 3 4 5; do
    python tools/simulate_light.py --device-id "SIM-0$i" --register \
        --admin-user admin --admin-password <password> --interval 5 &
done
```
Cek peta/grup sektor/grafik overview tidak silang data antar device, sekalian jadi
beban wajar buat ngerasain broadcast WebSocket paralel (`ws_manager.py`). Matikan
semua: `kill %1 %2 %3 %4 %5` atau `pkill -f simulate_light.py`.

## Membersihkan data uji

Tidak ada endpoint hapus device di API (disengaja - lihat `routes_provisioning.py`).
Bersihkan manual lewat `psql` setelah selesai tes:

```bash
docker exec postgres_db psql -U admin -d smart_lights -c \
  "DELETE FROM alerts WHERE device_id='SIM-01'; DELETE FROM devices WHERE device_id='SIM-01'; DELETE FROM sectors WHERE sector_name='Sektor 1 (Simulasi)';"
```

(Sektor cuma bisa dihapus kalau sudah nol device di dalamnya - hapus device dulu.)
