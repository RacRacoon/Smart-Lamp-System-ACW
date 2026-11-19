# 3. Protokol MQTT

## 3.1 Broker

| | Board NEMA | Backend |
|---|---|---|
| Host | `broker.hivemq.com` | `broker.hivemq.com` |
| Port | 8883, TLS | 1883, polos |
| Client ID | `nema01sultan2026` | `acw_python_ingest` |
| Clean session | Ya, `AT+QMTCFG="session",0,1` | Ya |

Broker publik ini tidak meminta kredensial. Siapa pun yang tahu nama topiknya
bisa membaca telemetri dan mengendalikan relai jala listrik. Konfigurasi ini cukup
untuk purwarupa, tetapi belum layak untuk pemasangan di lapangan. Lihat Bab 9.

Host dan port backend bisa ditimpa lewat environment variable `MQTT_HOST` dan
`MQTT_PORT`. Board memakai nilai yang dikompilasi di `main.c`, jadi
pergantian broker di sisi board menuntut flash ulang.

## 3.2 Topik

| Arah | Topik | Penerbit | Pelanggan |
|---|---|---|---|
| Naik | `iot/lights/{device_id}/telemetry` | Board | Backend, pola `iot/lights/+/telemetry` |
| Turun | `iot/lights/{device_id}/command` | Backend | Board |

`device_id` dibatasi `^[A-Za-z0-9._-]{1,64}$` di sisi backend
(`config.is_valid_device_id`). Batas itu menutup penyuntikan wildcard ke nama
topik: tanpa validasi, `device_id` berisi `+` atau `#` akan membuat backend
publish perintah ke banyak topik sekaligus.

## 3.3 Telemetri

Satu baris JSON, dirakit `mq_build_body()` di firmware. Panjangnya muat di
buffer 220 byte.

```json
{"id":"NEMA-01","volt":228.300,"current":0.248,"power":56.400,
 "dim":80,"relay":"on","auto":true,
 "lat":-7.314990,"lng":112.789501,"uptime":37221}
```

| Field | Tipe | Arti |
|---|---|---|
| `id` | string | Harus sama dengan `device_id` yang terdaftar di tabel `devices` |
| `volt` | number | Tegangan jala listrik, volt |
| `current` | number | Arus, ampere |
| `power` | number | Daya nyata, watt |
| `dim` | number | Kecerahan, persen (0 sampai 100) |
| `relay` | `"on"` atau `"off"` | Status relai saat pembacaan diambil |
| `auto` | boolean | Mode otomatis LDR |
| `lat`, `lng` | number | Letak tiang dari flash, derajat |
| `uptime` | number | Detik sejak board menyala |

Perhatikan tiga hal berikut saat membaca payload ini:

**`uptime` bukan usia pakai lampu.** Angka itu ter-reset tiap board dinyalakan
ulang. Backend tidak memakainya untuk `lamp_hours`, melainkan menjumlahkan
sendiri selisih antar telemetri lewat `db.accrue_lamp_hours()`.

**Tegangan nol punya dua arti.** Payload yang memang melaporkan 0 V berarti
jala listrik hilang. Payload yang tidak membawa field `volt` sama sekali juga
terbaca sebagai 0, dan itu bukan gangguan. Backend membedakan keduanya lewat
`volt_reported`.

**`dim` dalam persen, bukan per mille.** Firmware menyimpannya sebagai per
mille lalu membaginya 10 saat merakit payload.

## 3.4 Perintah

```json
{"relay": "on", "dim": 80, "auto": false}
```

| Field | Tipe | Arti |
|---|---|---|
| `relay` | `"on"` atau `"off"` | Menyalakan atau memadamkan relai |
| `dim` | number | Kecerahan persen, 0 sampai 100. Diabaikan selama `auto` menyala |
| `auto` | boolean | Menyalakan atau mematikan mode otomatis LDR |

Ketiganya opsional dan minimal satu harus ada. Backend menolak permintaan yang
tidak membawa satu pun dari ketiganya.

`mq_apply_command()` menjalankan relai lebih dulu, baru dim. Urutannya penting:
menyalakan lampu lalu menyetel kecerahannya dalam satu perintah harus berakhir
pada kecerahan itu, bukan pada nilai lama yang sempat terpasang sesaat.

Board melaporkan status barunya segera setelah menjalankan perintah, tanpa
menunggu giliran 60 detik berikutnya. Sifat itulah yang dipakai
`tools/cek_nema.py` untuk menguji arah turun.

## 3.5 QoS

| Pesan | QoS | Alasan |
|---|---|---|
| Telemetri dari board | 0 | Hilangnya satu laporan tidak merugikan, yang berikutnya 60 detik lagi |
| Subscribe telemetri backend | 1 | |
| Subscribe perintah di board | 1 | QoS 0 membuat perintah hilang diam-diam saat radio tersendat |
| Perintah dari backend | 1 | |

Subscribe perintah di board semula QoS 0. Gejalanya: tombol ditekan, dashboard
menjawab 200, lampu tidak berubah, dan tidak ada error di mana pun.

## 3.6 Retained message dan umurnya

Backend publish perintah dengan `retain=True`. Broker menahan pesan
terakhir di topik itu dan mengirimkannya ke board yang baru subscribe.

Tanpa itu, perintah yang dikirim ke board yang sedang kehilangan sesi akan
hilang. Dengan itu, perintah lama bisa hidup terlalu lama: `{"relay":"off"}`
yang tertinggal di broker memadamkan lampu tiap kali board menyambung ulang,
berhari-hari setelah tombolnya ditekan.

Dua mekanisme membatasinya:

1. `RETAINED_COMMAND_TTL_SECONDS` (300 detik). Backend menjadwalkan
   `_clear_retained_command()` yang publish payload kosong ke topik yang
   sama dengan `retain=True`, dan broker melupakan pesannya.
2. `_clear_orphan_retained_commands()`, dipanggil dari `_on_connect()`. Timer
   TTL mati bersama prosesnya, jadi backend yang baru hidup menyapu perintah
   tertinggal dari sesi sebelumnya.

## 3.7 Perintah dim dan jadwal

`publish_dim_command()` publish `{"dim": n}` dengan `retain=False`.
`publish_schedule_command()` publish `{"schedule": [...]}` dengan
`retain=True`, karena jadwal sektor memang harus diterima board yang baru
menyala.
