# Kontroler NEMA — APM32F103CBT6

Firmware pengendali lampu jalan pintar untuk soket NEMA. Satu papan mengurus
peredupan lampu, relai jala listrik, pembacaan daya, sensor lingkungan,
kemiringan tiang, jam, dan GPS — semuanya bisa dilihat dan disetir lewat satu
konsol UART.

| | |
|---|---|
| MCU | APM32F103CBT6 (Geehy, setara STM32F103CB) |
| Inti | Cortex-M3, 72 MHz |
| Flash | 128 KB — linker memakai **127 KB**, 1 KB terakhir untuk setelan |
| RAM | 20 KB |
| Pemakaian saat ini | flash 48 684 B (37 %), RAM 3 704 B (18 %) |
| Lingkungan | VS Code + EIDE, kerangka dari STM32CubeMX |
| Kompiler | arm-none-eabi-gcc 14.3, `-Og`, `nano.specs` + `nosys.specs` |

---

## 1. Peta kaki

```
PA2  USART2_TX ┐
PA3  USART2_RX ┘ konsol ke PC, 115200 8N1

PB10 USART3_TX ┐
PB11 USART3_RX ┘ GPS, 9600 8N1

PA9  USART1_TX ┐
PA10 USART1_RX ┘ power meter HLW8032, 4800 8N1
PB13           power factor, interupsi dua tepi

PA15           relai AC_SW      (RENDAH = lampu menyala)
PB1  TIM3_CH4  PWM peredup 200 Hz ke driver OSRAM 0-10 V (terbalik)
PB0  ADC1_IN8  LDR

PB6  I2C1_SCL ┐ 0x44 SHT30 suhu/kelembapan
PB7  I2C1_SDA ┘ 0x32 BL5372 RTC
                0x19 LIS3DH akselerometer

PB8            LED denyut        (aktif rendah)
PB9            LED cermin relai  (aktif rendah)

PA13 SWDIO ┐
PA14 SWCLK ┘ debug

PA4-PA7, PA11, PA12   W25Q64JV flash SPI — TERPASANG, BELUM DIPAKAI
```

**Catatan penting soal PA2/PA3.** Aslinya kaki itu untuk modem Quectel. Kartu
SIM-nya kedaluwarsa, modulnya dilepas, dan kabel USB-TTL ke PC menempati
tempatnya — sementara GPS pindah ke bekas soket konsol di PB10/PB11. Begitu
kartu baru datang, keduanya bertukar lagi.

**PB8/PB9 berlabel `GPS` dan `GPS_2` di CubeMX.** Nama itu keliru dan menyesatkan;
keduanya LED. GPS tidak mungkin di situ — pada F103 kaki PB8/PB9 tidak punya
fungsi USART sama sekali. Nama bawaan CubeMX dipakai apa adanya supaya
regenerate tidak memutus kompilasi, lalu diberi nama jujur lewat `#define` di
`main.c`.

---

## 2. Susunan berkas

```
Core/Src/main.c           hampir seluruh program, di dalam blok USER CODE
Core/Src/stm32f1xx_it.c   empat penangan interupsi, di USER CODE BEGIN 1
Core/Inc/main.h           nama kaki, dihasilkan CubeMX
STM32F104.ioc             berkas CubeMX
STM32F103CBTX_FLASH.ld    LENGTH = 127K, menyisakan halaman setelan
build/Debug/APM32_ACW.hex keluaran
```

Semua kode tulisan tangan hidup di dalam blok `USER CODE`, jadi regenerate dari
CubeMX tidak menghapusnya. Yang **harus** dijaga saat regenerate:

- NVIC untuk USART1, USART2, USART3, dan EXTI15_10 **jangan dicentang** di
  CubeMX. Penangannya ditulis tangan di `stm32f1xx_it.c`; kalau CubeMX ikut
  membuatnya, muncul simbol ganda dan linker gagal.
- `STM32F103CBTX_FLASH.ld` harus tetap 127K.

---

## 3. Interupsi

Keempatnya membaca register `DR` **langsung**, bukan lewat
`HAL_UART_Receive_IT()`. Alasannya nyata, bukan gaya: `printf` yang memblokir
memegang kunci HAL selama ia mengirim, sehingga pemasangan ulang HAL dari dalam
penangan akan mengembalikan `HAL_BUSY` dan penerimaan berhenti selamanya.
Membaca `DR` sekaligus menghapus bendera RXNE dan luapan, jadi penerimanya
pulih sendiri.

| Interupsi | Isi |
|---|---|
| `USART2_IRQHandler` | byte konsol → cincin 64 byte |
| `USART3_IRQHandler` | byte GPS → cincin 512 byte |
| `USART1_IRQHandler` | byte meter → bingkai 24 byte |
| `EXTI15_10_IRQHandler` | tepi PB13, dicatat dengan pencacah siklus DWT (72 MHz) |

---

## 4. Loop utama

Satu putaran 100 ms:

```
rx_service()      jalankan perintah konsol yang sudah lengkap
meter_service()   susun bingkai HLW8032
gps_service()     rakit kalimat NMEA, periksa checksum, urai
                  tiap 10 putaran: mode auto LDR, log opsional
                  tiap putaran: balik LED denyut PB8
```

LED denyut berkedip 5 kali per detik. Kalau kedipnya berhenti, loop membeku —
penanda hidup yang bisa dilihat tanpa mencolok apa pun.

---

## 5. Subsistem

### Peredup

TIM3_CH4 di PB1, ARR 3599, prescaler 99 → **200 Hz**. Frekuensi ini hasil
pengukuran, bukan tebakan: pada 20 kHz keluarannya cuma 37 mV karena tingkat
0–10 V bersambung opto tidak sanggup mengikuti PWM cepat.

Keluarannya **terbalik** (`dim_invert = 1`), jadi `d 0` gelap dan `d 1000`
terang penuh — sejalan dengan apa yang dilihat mata, bukan dengan duty di kaki.

### LDR dan mode otomatis

ADC1_IN8 di PB0, waktu cuplik 239,5 siklus. Pembagi LDR berimpedansi tinggi;
1,5 siklus bawaan CubeMX jauh terlalu pendek untuk kapasitor sample-and-hold.
F103 juga wajib kalibrasi mandiri sekali lewat `HAL_ADCEx_Calibration_Start()`.

Mode auto memetakan bacaan LDR ke tingkat lampu, bergerak paling banyak 20
per mil per detik supaya awan lewat tidak membuat lampu berkedip.

**LDR lebih kuat daripada tangan.** Selama auto menyala, `d` dan `r` ditolak
dengan alasan yang disebutkan. Dulu keduanya diam-diam mematikan auto — LDR
kehilangan kendali tanpa ada yang tahu. Mematikan auto sekarang harus disengaja
lewat `m 0`.

### Power meter

HLW8032 di USART1, 4800 8N1, bicara tanpa diminta dalam bingkai 24 byte
(byte[1] = 0x5A, checksum atas byte 2..22).

```
V = Vpar / Vreg * Kv
I = Ipar / Ireg * Ki
P = Ppar / Preg * Kv * Ki
```

`Kv` dan `Ki` bergantung pembagi tegangan dan trafo arus papan ini. Karena skala
daya **persis** hasil kali keduanya, faktor daya `P / (V * I)` membatalkan
keduanya — **PF tidak perlu kalibrasi sama sekali**.

Tanpa AC di masukannya, pencacah periode chip berjalan bebas dan menghasilkan
rasio kecil yang terlihat seperti tegangan sah. Karena itu apa pun di bawah 50 V
dianggap keadaan diam, bukan bacaan.

### Relai

PA15. Beban ada di kontak NC, jadi **RENDAH = lampu menyala**. Boot menyalakan
lampu: pengendali yang tidak pernah hidup meninggalkan jalan tetap terang, dan
kumparannya tidak menarik arus sampai lampu dipadamkan.

### Sensor I2C

SHT30 (0x44) butuh 20 ms konversi, CRC diperiksa. BL5372 (0x32) memakai
pengalamatan RS5C372: **penunjuk = nomor register × 16**. Bit mode 24 jam ada di
control2 bit 5; `rtc_set` dulu menulis nol ke seluruh register itu dan
melemparkan chip ke mode 12 jam — jam 16 terbaca `36` karena bendera PM ada di
bit 5 register jam. Sekarang mode 24 jam ditegakkan saat boot, bukan hanya saat
jam disetel.

LIS3DH (0x19) ±2 g, 4 mg per LSB, bit auto-increment 0x80 pada alamat register.
Sudut kemiringan dihitung dari hasil kali silang (sinus) di bawah 45° dan hasil
kali titik (kosinus) di atasnya, dengan tabel kosinus bulat — tanpa libm.

### GPS

USART3, 9600 baud. CubeMX membukanya di 115200 karena itu bawaannya, jadi
`gps_init()` membuka ulang di 9600 — di dalam blok USER CODE supaya regenerate
berikutnya tidak diam-diam mengembalikannya.

Tiap kalimat diperiksa checksum sebelum dipakai. Ini bukan kehati-hatian
berlebihan: di baud yang salah, derau tetap mengandung koma-koma yang terlihat
masuk akal, dan parser yang percaya begitu saja akan melaporkan posisi di tengah
samudra. Kalau byte masuk tapi tak satu pun lolos, programnya mengatakan terus
terang bahwa baudnya mungkin salah.

Yang dibaca: GGA (kualitas kunci, jumlah satelit, ketinggian, posisi), RMC
(posisi, tanggal), GSV (satelit **terlihat**, dijumlahkan antar rasi). Dua angka
itu berbeda artinya — "terlihat" nol berarti antena belum melihat langit, bukan
gagal mengunci.

**Letak tiang disimpan sekali.** Lampu jalan tidak bergerak, dan start dingin di
bawah atap bisa belasan menit atau tidak selesai sama sekali. `gps save`
menyimpan posisi ke halaman setelan; sesudah itu papan tahu letaknya sebelum
penerima melihat satu satelit pun. Kunci berikutnya yang menyimpang jauh dari
titik tersimpan dilaporkan sebagai `MOVED?` — tiang dipindah, atau perangkat
dicuri.

---

## 6. Setelan di flash

Halaman 1 KB terakhir, `0x0801FC00`. Linker sudah tidak membagikannya.

```c
magic     'NEMA'
version   4
met_kv    skala tegangan
tilt_x/y/z  gravitasi saat pemasangan, mg
tilt_set
met_ki    skala arus, 0 = belum pernah dikalibrasi
site_lat  letak tiang, per sejuta derajat   (v4)
site_lon                                     (v4)
site_set                                     (v4)
check     jumlah seluruh medan di atasnya
```

Salinan v2 dan v3 masih bisa dibaca: tiap versi hanya **menambah** medan di
belakang, jadi medan lama tetap di posisi yang sama dan papan yang diperbarui di
lapangan tidak kehilangan kalibrasinya. `CFG_VERSION` wajib dinaikkan setiap ada
medan baru — salinan lama lalu diabaikan, bukan dibaca lewat tata letak yang
salah.

Tiap medan diperiksa jangkauannya sendiri-sendiri, jadi satu nilai rusak tidak
menyeret yang lain.

---

## 7. Konsol

115200 8N1 di PA2/PA3. Tekan `?` untuk daftar penuh. **Huruf tanpa angka
bertanya, bukan menyetel** — `d` sendirian melaporkan kecerahan, tidak
menolkannya.

```
LAMPU        d <0-1000>   r <0-3599>   m / m 1 / m 0
             b <raw>   n <raw>   g   i   1 / 0 / t
PEMBACAAN    s   l   y   w   a   j
SETELAN      c <n>   ci <mA>   cw <W>   zero   save   set YYMMDDhhmmss
GPS          gps   gps raw   gps save   gps <baud>   gps l
DIAGNOSTIK   z   o <addr> <reg>   k   u <baud>   v   x   e <hex>
             f <psc>   p   ? / h
```

Perintah berhuruf banyak (`gps`, `cw`, `ci`, `set`, `save`, `zero`) ditangani
sebelum switch huruf tunggal. Huruf kedua yang berupa huruf langsung ditolak:
dulu `zzz` memindai bus I2C dan `AT` menyalakan log LDR, karena hanya huruf
pertama yang dilihat.

---

## 8. Cetak tanpa dukungan float

`printf` di sini newlib-nano tanpa float — `%f` tidak mencetak apa pun. Angka
pecahan dicetak lewat pembantu yang memisahkan bagian bulat dan pecahannya:
`put_fixed()` untuk besaran listrik, `put_udeg()` untuk koordinat. Tandanya
diurus sebelum pemisahan, supaya -0,5 tidak keluar sebagai `0.-500000`.

---

## 9. Menyalakan dan memprogram

**Flash lewat OpenOCD jalur DAP langsung**, bukan STM32_Programmer_CLI:

```
openocd -s <st_scripts> -f ocd_sys.cfg \
        -c "program build/Debug/APM32_ACW.hex verify reset exit"
```

```tcl
source [find interface/stlink-dap.cfg]
transport select dapdirect_swd
source [find target/stm32f1x.cfg]
reset_config none separate
cortex_m reset_config sysresetreq
adapter speed 480
```

Dua jebakan yang sudah memakan waktu berjam-jam:

**STM32_Programmer_CLI menggeser transfer borongan pada probe klon ini** — baik
baca maupun tulis. Verifikasinya melaporkan selisih palsu, dan tulisannya
menaruh blok di alamat yang salah sehingga program gagal boot meski alat bilang
"Verified OK". Baca kecil (`-r32`, ≤ 64 byte) tetap tepat dan bisa dipercaya.

**`reset_config srst_only` tidak mereset apa pun** karena kaki NRST tidak
tersambung ke probe. Inti tetap terkunci di HardFault dan terlihat seperti
firmware mati, padahal flash-nya benar. Karena itu reset dilakukan lewat inti
(`sysresetreq`).

Aturan yang berlaku: **jangan percaya hasil verifikasi alat** — buktikan flash
berhasil dengan berbicara ke firmware-nya.

---

## 10. Jalur ke dashboard

Selama modem belum berkartu, PC menjadi jembatan:

```
papan  --UART-->  nema_serial_bridge.py  --MQTT-->  backend  -->  dashboard
       <--UART--                          <--MQTT--
```

Skrip ada di repo dashboard, `python-backend/tools/nema_serial_bridge.py`. Ia
mengetik `s` ke konsol tiap 10 detik, mengurai laporannya, lalu menerbitkannya
ke `iot/lights/NEMA-01/telemetry`. Ke arah sebaliknya ia berlangganan
`iot/lights/NEMA-01/command` dan menerjemahkan perintah dashboard jadi ketikan
konsol — kecerahan persen menjadi `d` per mil, dan mode auto menjadi `m`.

Bentuk muatannya sengaja disamakan dengan yang nanti dikirim papan sendiri lewat
`AT+QMTPUB`. Begitu kartu SIM baru terpasang, jembatan dimatikan dan backend
tidak perlu diubah sama sekali.

---

## 11. Yang belum dikerjakan

- **W25Q64JV** di PA4–PA7, PA11, PA12 belum disentuh — SPI1 belum dihidupkan di
  CubeMX. Calon pemakaian: menampung telemetri saat jaringan putus, lalu
  dikirim menyusul.
- **Mesin keadaan AT yang tidak memblokir** untuk modem: mendaftar, menerbitkan
  berkala, menyambung ulang. Menunggu kartu SIM.
- **Pelaporan gangguan lewat MQTT.** Sekarang HardFault dilaporkan ke konsol.
  Begitu modem kembali ke PA2/PA3, konsol itu hilang — laporannya harus ikut
  pindah ke muatan telemetri.
- **Kanal kehangatan warna.** Papan ini hanya punya satu keluaran PWM; mengatur
  warna butuh dua kanal. Slider CCT di dashboard belum berfungsi.
