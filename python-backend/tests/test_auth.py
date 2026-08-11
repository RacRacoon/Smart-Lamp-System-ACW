"""Test auth.py: hashing (argon2id + legacy scrypt), sesi, dan celah timing username
enumeration yang ditutup di sesi kerja sebelumnya (verify_password harus SELALU
dipanggil, walau user tidak ketemu - lihat auth.DUMMY_HASH)."""
import hashlib
import time

import pytest

import auth


def test_hash_and_verify_roundtrip():
    hashed = auth.hash_password("password-benar")
    assert auth.verify_password("password-benar", hashed) is True
    assert auth.verify_password("password-salah", hashed) is False


def test_hash_is_argon2id():
    hashed = auth.hash_password("apa saja")
    assert hashed.startswith("$argon2id$")
    assert auth.is_legacy_hash(hashed) is False


def test_legacy_scrypt_hash_masih_bisa_diverifikasi():
    # Meniru persis format lama dari Node crypto.scryptSync: salt disimpan sebagai
    # STRING HEX, tapi dipakai sebagai UTF-8 saat jadi salt (bukan di-decode ke bytes) -
    # lihat catatan _verify_legacy_scrypt() di auth.py.
    salt = "deadbeef"
    derived = hashlib.scrypt(
        "password-lama".encode("utf-8"), salt=salt.encode("utf-8"),
        n=auth.SCRYPT_N, r=auth.SCRYPT_R, p=auth.SCRYPT_P,
        maxmem=auth.SCRYPT_MAXMEM, dklen=auth.SCRYPT_DKLEN,
    )
    legacy_hash = f"{salt}:{derived.hex()}"

    assert auth.is_legacy_hash(legacy_hash) is True
    assert auth.verify_password("password-lama", legacy_hash) is True
    assert auth.verify_password("password-salah", legacy_hash) is False


def test_verify_password_hash_kosong_tidak_meledak():
    assert auth.verify_password("apa saja", "") is False
    assert auth.verify_password("apa saja", None) is False


def test_dummy_hash_dipakai_buat_samakan_waktu_login():
    # DUMMY_HASH harus hash argon2id yang SAH - kalau bukan, verify_password() bakal
    # ambil jalur cepat is_legacy_hash()/gagal parse alih-alih ikut jalur argon2 penuh,
    # dan gunanya (samakan waktu proses dengan user yang beneran ada) hilang.
    assert auth.DUMMY_HASH.startswith("$argon2id$")
    assert auth.verify_password("password apa saja", auth.DUMMY_HASH) is False


def test_session_issue_get_dan_expire():
    token = auth.issue_session("admin")
    session = auth.get_session(token)
    assert session is not None
    assert session.role == "admin"
    assert auth.is_admin(token) is True

    # Sesi role "user" bukan admin
    user_token = auth.issue_session("user")
    assert auth.is_admin(user_token) is False


def test_session_expired_tidak_valid_lagi():
    token = auth.issue_session("admin")
    auth._sessions[token].expires_at = time.time() - 1  # paksa kedaluwarsa
    assert auth.get_session(token) is None
    assert auth.is_admin(token) is False


def test_invalidate_session_mencabut_token():
    token = auth.issue_session("admin")
    assert auth.is_admin(token) is True

    auth.invalidate_session(token)

    assert auth.get_session(token) is None
    assert auth.is_admin(token) is False


def test_invalidate_session_token_kosong_tidak_meledak():
    auth.invalidate_session(None)
    auth.invalidate_session("tok_tidak_pernah_ada")  # tidak boleh raise
