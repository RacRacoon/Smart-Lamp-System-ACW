"""Test end-to-end lewat HTTP (TestClient): /api/login, /api/logout, dan properti
timing-safety yang diperbaiki sesi kerja sebelumnya - verify_password() harus SELALU
dipanggil, walau username tidak ada, supaya waktu respons tidak bisa dipakai
enumerasi username."""
import auth
import config


def test_login_sukses_dapat_token_dan_role(client, fake_users):
    fake_users["admin"] = {
        "username": "admin", "role": "admin",
        "password_hash": auth.hash_password("rahasia123"),
    }
    r = client.post("/api/login", json={"username": "admin", "password": "rahasia123"})
    assert r.status_code == 200
    body = r.json()
    assert body["role"] == "admin"
    assert body["token"].startswith("tok_")


def test_login_password_salah_401_pesan_generik(client, fake_users):
    fake_users["admin"] = {
        "username": "admin", "role": "admin",
        "password_hash": auth.hash_password("rahasia123"),
    }
    r = client.post("/api/login", json={"username": "admin", "password": "salah"})
    assert r.status_code == 401
    assert r.json() == {"error": "Username atau password salah"}


def test_login_username_tidak_ada_pesan_sama_dengan_password_salah(client, fake_users):
    r = client.post("/api/login", json={"username": "tidak_ada", "password": "apa saja"})
    assert r.status_code == 401
    assert r.json() == {"error": "Username atau password salah"}


def test_login_field_kosong_400(client):
    r = client.post("/api/login", json={"username": "", "password": ""})
    assert r.status_code == 400


def test_verify_password_selalu_dipanggil_walau_user_tidak_ada(client, fake_users, monkeypatch):
    """INI test regresi buat celah timing-enumeration yang ditutup sesi kerja
    sebelumnya. Sebelum diperbaiki: `if not user or not verify_password(...)` pendek-
    sirkuit, verify_password() TIDAK PERNAH dipanggil kalau user tidak ketemu - waktu
    respons jadi beda jauh dari kasus password salah (yang argon2id-nya jalan penuh).
    Assert di sini bukan ukur waktu (tidak stabil buat CI), tapi pastikan fungsi
    hashing-nya benar dipanggil di kedua kasus - itu prasyarat supaya waktunya mirip."""
    calls = []
    original = auth.verify_password

    def spy(password, stored_hash):
        calls.append(stored_hash)
        return original(password, stored_hash)

    monkeypatch.setattr(auth, "verify_password", spy)

    client.post("/api/login", json={"username": "user_tidak_ada", "password": "x"})
    assert len(calls) == 1
    assert calls[0] == auth.DUMMY_HASH  # dummy hash dipakai persis buat kasus ini


def test_login_dibatasi_rate_limit(client, fake_users):
    config.RATE_LIMIT_LOGIN_MAX = 3
    config.RATE_LIMIT_LOGIN_WINDOW = 60
    for _ in range(3):
        r = client.post("/api/login", json={"username": "x", "password": "y"})
        assert r.status_code == 401
    r = client.post("/api/login", json={"username": "x", "password": "y"})
    assert r.status_code == 429


def test_logout_mencabut_sesi_di_server(client, fake_users, admin_token):
    # Buktikan token admin_token valid dulu (lewat endpoint admin-only)
    r = client.post("/api/sectors", json={"sector_name": "Tes"},
                     headers={"X-ACW-Token": admin_token})
    assert r.status_code != 403  # gagal-nya boleh 500 (db.create_sector belum di-stub), asal bukan Forbidden

    r = client.post("/api/logout", headers={"X-ACW-Token": admin_token})
    assert r.status_code == 200
    assert r.json() == {"ok": True}

    # Token yang sama sekarang HARUS ditolak - buktikan logout benar mencabut sesi
    # di server, bukan cuma dilupakan di sisi klien (celah yang ditutup sesi kerja lalu).
    r = client.post("/api/sectors", json={"sector_name": "Tes2"},
                     headers={"X-ACW-Token": admin_token})
    assert r.status_code == 403


def test_logout_token_kosong_tetap_200(client):
    r = client.post("/api/logout")
    assert r.status_code == 200
