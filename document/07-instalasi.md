# 7. Instalasi dan menjalankan sistem

Cara yang dipakai sehari-hari di proyek ini: Windows tanpa Docker, tiap bagian
berjalan langsung di mesin. `README.md` di akar repo memuat versi Docker dan
langkah pemasangan PostgreSQL yang lebih rinci.

## 7.1 Prasyarat perangkat lunak

| Software | Versi | Catatan |
|---|---|---|
| PostgreSQL | 16 atau 17 | `winget install --id PostgreSQL.PostgreSQL.17` |
| Python | 3.11 | `winget install --id Python.Python.3.11` |
| Node.js | mana saja yang mutakhir | Hanya untuk menjalankan tes frontend |

Python 3.13 dan di atasnya belum punya wheel `psycopg2-binary`, sehingga pip
akan mencoba kompilasi dari sumber dan gagal.

## 7.2 Menyiapkan database

```powershell
$psql = "C:\Program Files\PostgreSQL\17\bin\psql.exe"

& $psql -U postgres -h 127.0.0.1 -c "CREATE ROLE admin LOGIN PASSWORD 'ACW123' SUPERUSER;"
& $psql -U postgres -h 127.0.0.1 -c "CREATE DATABASE smart_lights OWNER admin;"

$env:PGPASSWORD = "ACW123"
& $psql -U admin -h 127.0.0.1 -d smart_lights -f python-backend\schema.sql
& $psql -U admin -h 127.0.0.1 -d smart_lights -f python-backend\schema_indexes.sql
```

`schema.sql` hanya memindahkan bentuk tabel, bukan isinya. Database yang baru
dibuat kosong termasuk tabel `users`, dan login apa pun akan ditolak sampai
akun dibuat.

## 7.3 Akun login pertama

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

Hasilnya akun `admin` berperan admin dengan password `ACW123`.

Nilai itu hanya pemancing untuk mengisi tabel `users` yang masih kosong. Di
mesin pengembangan ini password `admin` dan `monitoring` sudah diganti lewat
`tools/ganti_password.py`, dan nilai barunya tidak disimpan di repo maupun di
dokumen ini. Ganti juga sebelum sistem dipakai di luar mesin pengembangan,
lalu catat nilainya di pengelola password, bukan di berkas proyek.

## 7.4 Akun monitoring

Dashboard mengenal dua role, dan `users_role_check` di skema membatasi kolomnya
ke dua nilai itu saja:

| Role | Yang bisa dilakukan |
|---|---|
| `admin` | Semuanya: Kendali Cepat, Kelola Lampu, jadwal sektor, hapus peringatan |
| `user` | Hanya membaca, plus menandai peringatan terbaca |

Buat akun read-only dengan `tools/ganti_password.py`. Passwordnya ditanyakan
lewat `getpass`, bukan lewat argumen baris perintah, supaya tidak tersimpan di
riwayat shell dan tidak terbaca di daftar proses:

```powershell
cd python-backend
& $vpy tools\ganti_password.py monitoring --role user
```

Skrip yang sama mengganti password akun yang sudah ada. Tanpa `--role`, role
akun lama dipertahankan, dan akun baru dibuat sebagai `user`.

Skrip ini dipakai saat tabel `users` masih kosong atau saat password hilang.
Sesudah bisa login, penggantian password sehari-hari lewat halaman Pengaturan
Akun di dashboard, yang memanggil `POST /api/change-password` dan mencabut
sesi lain milik akun itu. Lihat subbab 4.2 dan 6.1.

Catatan sesudah mengganti password: sesi yang masih hidup
tidak ikut dicabut. `auth.py` menyimpan sesi di memori proses backend, dan
skrip itu proses lain. Restart backend untuk memaksa semua orang login ulang.

## 7.5 Menjalankan sistem

```text
run-dashboard-windows.bat
```

Skrip itu mengerjakan lima hal:

1. Mencari layanan PostgreSQL (namanya ikut versi, jadi dicari bukan ditulis
   mati) dan menyalakannya kalau belum jalan.
2. Membuat venv Python 3.11 di `%USERPROFILE%\.venvs\acw` kalau belum ada, lalu
   memasang dependensi. Venv sengaja di luar folder repo, karena isinya ribuan
   berkas kecil dan folder repo ada di OneDrive.
3. Menyalakan backend di port 8000 di jendela terpisah.
4. Menyalakan server statis frontend di port 5500.
5. Membuka browser ke `http://localhost:5500`.

Hentikan dengan menutup jendela-jendela berjudul "ACW ...".

### Variabel yang bisa diubah

Setel sebelum menjalankan skrip, misalnya
`set MQTT_HOST=broker-sendiri.local && run-dashboard-windows.bat`.

| Variabel | Bawaan |
|---|---|
| `DB_HOST`, `DB_PORT` | `127.0.0.1`, `5432` |
| `DB_NAME`, `DB_USER`, `DB_PASSWORD` | `smart_lights`, `admin`, `ACW123` |
| `MQTT_HOST`, `MQTT_PORT` | `broker.hivemq.com`, `1883` |
| `API_HOST`, `API_PORT` | `127.0.0.1`, `8000` |
| `WEB_PORT` | `5500` |
| `VENV_DIR` | `%USERPROFILE%\.venvs\acw` |
| `NEMA_BRIDGE`, `NEMA_PORT`, `NEMA_DEVICE` | `0`, `COM6`, `NEMA-01` |

Jangan kembalikan `MQTT_HOST` ke `broker.emqx.io`. Backend yang tersambung ke
sana tetap menyala mulus, tetap melaporkan "terhubung", lalu publish
perintah relai ke broker orang lain. Board tidak pernah menerimanya dan tidak
ada satu pun error yang muncul. Sudah terjadi pada 13 Oktober 2026, dan
gejalanya terbaca seperti board NEMA yang membandel.

## 7.6 Konfigurasi asisten AI

Tanpa kunci, endpoint analisis dan chat menjawab 503 dan sisa dashboard
berjalan normal. Pasang kuncinya sebagai environment variable Windows, bukan di
dalam berkas `.bat` yang masuk git:

```powershell
setx GEMINI_API_KEY "isi-kunci-di-sini"
```

Provider yang sudah diperiksa bentuk API-nya:

| Provider | `GEMINI_BASE_URL` | `GEMINI_MODEL` |
|---|---|---|
| Google AI Studio | `https://generativelanguage.googleapis.com/v1beta/openai` | `gemini-flash-lite-latest` |
| Groq | `https://api.groq.com/openai/v1` | `openai/gpt-oss-120b` |

Ketiganya harus diganti bersama-sama. Kunci satu provider tidak berlaku di
provider lain, dan nama modelnya berbeda.

`ai_chat.py` tidak memakai SDK apa pun, hanya `httpx` ke `/chat/completions`.
Siapa pun yang menyediakan endpoint OpenAI-compatible dengan tool-calling dan
streaming bisa dipasang tanpa menyentuh satu baris kode.

Batas gratis Groq yang mengikat adalah 8.000 token per menit, jadi
`RATE_LIMIT_AI_MAX` perlu diturunkan dari 20 kalau penyedianya dipindah ke
sana.

## 7.7 Jembatan serial (jalur darurat)

`python-backend/tools/nema_serial_bridge.py` menghubungkan konsol UART board ke
broker MQTT dua arah, tanpa mengubah board sama sekali. Skrip itu mengetikkan
perintah ke konsol seperti manusia: `s` untuk membaca status, `d <permil>`
untuk mengubah kecerahan.

Dipakai sebelum kartu SIM aktif terpasang pada 12 Oktober 2026. Sejak itu board
publish telemetrinya sendiri lewat modem 4G, dan jembatan ini hanya untuk
keadaan darurat, misalnya board tanpa sinyal yang perlu ditanya lewat kabel.
Bentuk payload yang dihasilkannya sama persis dengan yang dikirim board.

```text
set NEMA_BRIDGE=1
run-dashboard-windows.bat
```

## 7.8 Simulator lampu

`python-backend/tools/simulate_light.py` publish telemetri palsu untuk
menguji dashboard tanpa perangkat keras.

```bash
python tools/simulate_light.py --device-id SIM-01 --register \
    --admin-user admin --admin-password ACW123
```

`--register` mendaftarkan sektor dan perangkatnya lewat API lebih dulu. Tanpa
itu, telemetrinya akan ditolak backend dan memicu peringatan
`Perangkat Tidak Terdaftar`, yang juga berguna untuk menguji jalur penolakan.
Rincian lain ada di `python-backend/tools/TESTING.md`.
