# `schema.sql` - Cetak Biru Database

## Kenapa file ini ada

Sampai 13 Agustus 2026, struktur tabel database (`CREATE TABLE`, kolom, primary key,
foreign key) **tidak ada di manapun di repo ini**. `schema_indexes.sql` sudah lama ada,
tapi komentarnya sendiri bilang jelas: index tambahan itu, bukan skema tabelnya.
Skema aslinya cuma "hidup" di database `smart_lights` yang kebetulan sedang jalan di
container `postgres_db`.

Artinya: kalau laptop ini rusak, kalau database perlu dibangun ulang dari nol, atau
kalau proyek ini pindah ke server produksi - tidak ada cetak biru yang bisa dipakai.
Satu-satunya cara tahu struktur tabelnya adalah connect langsung ke database yang
jalan dan `\d` satu-satu.

`schema.sql` menutup itu. Isinya diambil dari `pg_dump --schema-only` terhadap
database live, lalu dirapikan manual (urutan tabel ikut alur data, komentar
ditambahkan) - **bukan skema yang diinginkan, tapi skema yang beneran ada**,
diverifikasi ulang persis sama (lihat bagian "Sudah diverifikasi" di bawah).

## Struktur data (ringkas)

```
 users                          sectors
 (login: admin / user)          (area PJU, mis. "Sektor 1 (Jalan Tunjungan)")
                                     │
                                     │ sector_name
                        ┌────────────┼─────────────────┐
                        │ ON DELETE SET NULL            │ ON DELETE CASCADE
                        ▼                                ▼
                    devices                      sector_schedules
                    (satu baris per tiang         (jadwal RTC per sektor,
                     lampu, device_id PK)          3-6 fase/hari)
                        │
              ┌─────────┴──────────┐
              │ ON DELETE CASCADE  │ ON DELETE CASCADE
              ▼                    ▼
           alerts             telemetry_logs
        (riwayat alert)      (histori sensor -
                              tabel paling cepat
                              tumbuh)
```

Detail tiap kolom, kenapa suatu `ON DELETE` dipilih `SET NULL` vs `CASCADE`, dan
index apa yang wajib ada - semua sudah dikomentari langsung di `schema.sql`, tidak
diulang di sini supaya tidak ada dua sumber kebenaran yang bisa saling beda.

## Cara pakai

### Bangun database baru dari nol

```bash
# 1. Pastikan Postgres kosong sudah jalan (mis. lewat docker-compose.yml di luar repo)
# 2. Buat database-nya
psql -U admin -h localhost -c "CREATE DATABASE smart_lights;"
# 3. Restore skemanya
psql -U admin -h localhost -d smart_lights -f python-backend/schema.sql
```

Lewat Docker (kalau Postgres jalan di container `postgres_db`):

```bash
docker exec postgres_db psql -U admin -c "CREATE DATABASE smart_lights;"
docker exec -i postgres_db psql -U admin -d smart_lights < python-backend/schema.sql
```

File ini cuma bikin STRUKTUR tabel - kosong tanpa data. Baris pertama yang harus
ditambah manual sesudahnya: satu akun admin di tabel `users` (lihat `auth.py` buat
cara generate hash argon2id-nya).

### Menjaga file ini tetap akurat

Tidak ada tool migrasi (Alembic dkk) di proyek ini - jadi tidak ada yang otomatis
menjaga `schema.sql` tetap sinkron dengan database live. Aturan mainnya manual:

**Kalau kamu `ALTER TABLE` langsung ke database yang jalan, update `schema.sql` di
commit yang sama.** Jangan ditunda "nanti sekalian" - itu persis kenapa file ini
sempat tidak ada sama sekali sebelumnya.

Buat cek apakah `schema.sql` masih sinkron dengan database live kapan saja:

```bash
docker exec postgres_db pg_dump -U admin -d smart_lights --schema-only \
  --no-owner --no-privileges > /tmp/live_schema_check.sql
diff <(grep -v restrict /tmp/live_schema_check.sql) \
     <(grep -v restrict python-backend/schema.sql)
```

Diff kosong (exit code 0) berarti masih sinkron. Kalau ada beda, `schema.sql` sudah
ketinggalan - update manual mengikuti struktur live saat itu.

### Sudah diverifikasi

`schema.sql` sudah dites bukan cuma "kelihatan benar" - direstore ke database kosong
terpisah (`schema_test`), di-dump ulang, dibandingkan `diff` baris-per-baris dengan
dump asli dari database live. Hasilnya identik (exit code 0), lalu database ujinya
dihapus. Prosedur yang sama bisa diulang kapan saja pakai perintah di atas.

## Hubungan dengan `schema_indexes.sql`

`schema_indexes.sql` tetap ada, tidak dihapus - isinya (index `telemetry_logs` &
`alerts`) sudah ikut dimasukkan ke `schema.sql` juga, jadi ada duplikasi kecil yang
disengaja: `schema.sql` restore-nya idempoten kalau `schema_indexes.sql` dijalankan
lagi sesudahnya (`CREATE INDEX IF NOT EXISTS`, tidak akan error). Perbedaannya:
`schema_indexes.sql` fokus ke *alasan* tiap index ada (histori kenapa dan kapan
ditambahkan), `schema.sql` adalah snapshot struktur LENGKAP - tabel jadi kalau mau
tahu "database ini bentuknya apa", lihat `schema.sql`.

## Yang belum diselesaikan file ini

Jujur, biar tidak ada ekspektasi salah:

- **Bukan migrasi beneran.** Ini snapshot sekali jalan, bukan riwayat perubahan
  bertahap (Alembic dkk punya versi `v1 -> v2 -> v3`). Kalau proyek ini tumbuh lebih
  besar dan butuh histori perubahan skema yang terlacak, alat migrasi beneran
  adalah langkah berikutnya - bukan diselesaikan file ini.
- **Tanpa kebijakan retensi `telemetry_logs`.** Tabel ini tumbuh tercepat (satu
  baris per pembacaan MQTT tiap lampu) dan belum ada strategi arsip/hapus data
  lama - dicatat di komentar `schema.sql`, belum ditindaklanjuti.
- **Aturan validasi Python (charset device_id, rentang dim/cct) tidak ikut jadi
  `CHECK` constraint di database** - divalidasi di lapisan aplikasi saja
  (`config.is_valid_device_id`, `Field(ge=..., le=...)` di route Pydantic). Baris
  yang masuk lewat jalur lain (`psql` manual, migrasi lama) bisa saja melewati
  validasi itu.
