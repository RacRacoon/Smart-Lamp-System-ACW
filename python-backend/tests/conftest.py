"""
Fixture bersama. TestClient dipakai TANPA context manager ("with TestClient(app)")
supaya event startup (db.init_pool, koneksi MQTT sungguhan) tidak ikut jalan - test-test
di sini murni logika Python (auth, rate limit, validasi), tidak butuh Postgres/MQTT
beneran. Fungsi db.* di-monkeypatch per-test yang butuh saja.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

import auth
import config
import main


@pytest.fixture(autouse=True)
def _reset_shared_state():
    """auth._sessions, rate_limit._hits, auth._consecutive_login_failures - semua dict
    module-level. Tanpa reset ini, test yang jalan duluan bisa nyisain sesi/hit-count/
    hitungan gagal yang bikin test SESUDAHNYA gagal/lolos keliru."""
    import rate_limit
    auth._sessions.clear()
    auth._consecutive_login_failures.clear()
    rate_limit._hits.clear()
    yield
    auth._sessions.clear()
    auth._consecutive_login_failures.clear()
    rate_limit._hits.clear()


@pytest.fixture
def client():
    return TestClient(main.app, raise_server_exceptions=False)


@pytest.fixture
def fake_users(monkeypatch):
    """Simulasikan tabel users tanpa Postgres beneran. Dict-nya dibalikin biar test bisa
    nambah/ubah user setelah fixture dipanggil."""
    store: dict[str, dict] = {}

    def get_user_by_username(username):
        return store.get(username)

    def update_password_hash(username, new_hash):
        if username in store:
            store[username]["password_hash"] = new_hash

    import db
    monkeypatch.setattr(db, "get_user_by_username", get_user_by_username)
    monkeypatch.setattr(db, "update_password_hash", update_password_hash)
    return store


@pytest.fixture
def admin_token(fake_users):
    """Daftarkan admin argon2id + login beneran lewat auth.issue_session - dipakai test
    yang butuh token admin valid tanpa peduli detail login itu sendiri."""
    fake_users["admin"] = {
        "username": "admin",
        "role": "admin",
        "password_hash": auth.hash_password("admin-secret-123"),
    }
    return auth.issue_session("admin")
