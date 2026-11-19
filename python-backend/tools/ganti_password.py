#!/usr/bin/env python3
"""Buat akun dashboard atau ganti passwordnya.

Dipakai untuk dua hal: menambah akun monitoring (role `user`, read-only) dan
mengganti password akun yang sudah ada. Keduanya menulis hash argon2id lewat
auth.hash_password(), sama persis dengan jalur login, jadi tidak ada format
hash kedua yang perlu dijaga.

Passwordnya TIDAK diketik di baris perintah. Argumen baris perintah terbaca di
daftar proses dan tersimpan di riwayat shell; skrip ini menanyakannya lewat
getpass, yang tidak menampilkan ketikan dan tidak meninggalkan jejak.

    python tools/ganti_password.py monitoring --role user
    python tools/ganti_password.py admin

Tanpa --role, role akun yang sudah ada dipertahankan. Akun baru tanpa --role
dibuat sebagai `user`, bukan `admin`: kalau rolenya lupa disebut, yang lebih
aman adalah akun yang tidak bisa mengubah apa-apa.
"""
import argparse
import getpass
import os
import sys

import psycopg2

# auth.py dan config.py ada satu tingkat di atas folder tools/. Python menaruh
# folder SKRIP di sys.path, bukan folder kerja, jadi keduanya tidak ketemu tanpa
# baris ini, apa pun direktori tempat skrip dipanggil.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import auth
import config

ROLE_SAH = ("admin", "user")


def main() -> int:
    p = argparse.ArgumentParser(description="Buat akun dashboard atau ganti passwordnya.")
    p.add_argument("username")
    p.add_argument("--role", choices=ROLE_SAH, default=None,
                   help="admin (akses penuh) atau user (monitoring, read-only)")
    args = p.parse_args()

    sandi = getpass.getpass("Password baru untuk '%s': " % args.username)
    if len(sandi) < 8:
        print("!! Password minimal 8 karakter.", file=sys.stderr)
        return 1
    if sandi != getpass.getpass("Ulangi: "):
        print("!! Kedua ketikan berbeda.", file=sys.stderr)
        return 1

    try:
        c = psycopg2.connect(host=config.DB_HOST, port=config.DB_PORT,
                             dbname=config.DB_NAME, user=config.DB_USER,
                             password=config.DB_PASSWORD)
    except psycopg2.OperationalError as e:
        print("!! Database tidak bisa dihubungi: %s" % e, file=sys.stderr)
        return 1

    with c:
        cur = c.cursor()
        cur.execute("SELECT role FROM users WHERE username = %s", (args.username,))
        baris = cur.fetchone()
        hash_baru = auth.hash_password(sandi)

        if baris:
            role = args.role or baris[0]
            cur.execute("UPDATE users SET password_hash = %s, role = %s WHERE username = %s",
                        (hash_baru, role, args.username))
            print("Password '%s' diganti. Role: %s." % (args.username, role))
            # Sesi yang masih hidup TIDAK ikut dicabut: auth.py menyimpannya di
            # memori proses, dan skrip ini proses lain. Restart backend untuk
            # memaksa semua orang login ulang.
            print("Sesi yang sedang berjalan masih berlaku sampai backend di-restart.")
        else:
            role = args.role or "user"
            cur.execute("INSERT INTO users (username, password_hash, role) VALUES (%s, %s, %s)",
                        (args.username, hash_baru, role))
            print("Akun '%s' dibuat dengan role %s." % (args.username, role))

    c.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
