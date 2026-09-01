"""Test end-to-end lewat HTTP (TestClient): /api/login, /api/logout, dan properti
timing-safety yang diperbaiki sesi kerja sebelumnya - verify_password() harus SELALU
dipanggil, walau username tidak ada, supaya waktu respons tidak bisa dipakai
enumerasi username."""
import auth
import config
import ws_manager


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
    body = r.json()
    # retry_after_seconds angka murni (bukan cuma teks) - script.js handleLogin()
    # pakai ini buat hitung-mundur kunci tombol submit, bukan parse teks pesan.
    assert isinstance(body["retry_after_seconds"], int)
    assert body["retry_after_seconds"] > 0
    assert str(body["retry_after_seconds"]) in body["error"]


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


def test_alert_terpicu_tepat_di_kegagalan_ke_3(client, fake_users, monkeypatch):
    """Regresi buat fitur peringatan login gagal berulang - dipicu TEPAT di kelipatan
    3 (3, 6, ...), tidak lebih cepat, tidak lebih lambat."""
    # Dinaikkan tinggi biar rate limit per-IP (fitur BEDA, lihat test_login_dibatasi_
    # rate_limit) tidak ikut motong percobaan sebelum sempat kehitung di sini.
    config.RATE_LIMIT_LOGIN_MAX = 100
    import db
    inserted = []
    broadcasted = []
    monkeypatch.setattr(db, "insert_alert", lambda *a, **kw: inserted.append(a))
    monkeypatch.setattr(ws_manager, "broadcast", lambda payload: broadcasted.append(payload))

    for i in range(1, 3):
        client.post("/api/login", json={"username": "admin", "password": f"salah{i}"})
        assert inserted == [], f"belum boleh terpicu di kegagalan ke-{i}"
        assert broadcasted == []

    client.post("/api/login", json={"username": "admin", "password": "salah3"})
    assert len(inserted) == 1
    assert len(broadcasted) == 1
    assert broadcasted[0]["alertType"] == "repeated_login_failure"
    assert broadcasted[0]["device_id"] == "admin"
    assert "id" not in broadcasted[0]  # sengaja - "id" trigger dashboard daftarkan device baru
    assert "3 percobaan" in broadcasted[0]["message"]


def test_alert_tidak_terpicu_lagi_di_kegagalan_ke_4_dan_5(client, fake_users, monkeypatch):
    config.RATE_LIMIT_LOGIN_MAX = 100
    import db
    inserted = []
    monkeypatch.setattr(db, "insert_alert", lambda *a, **kw: inserted.append(a))
    monkeypatch.setattr(ws_manager, "broadcast", lambda payload: None)

    for i in range(1, 6):
        client.post("/api/login", json={"username": "admin", "password": f"salah{i}"})
    assert len(inserted) == 1  # cuma sekali (di kegagalan ke-3), belum lagi sampai ke-6


def test_login_sukses_reset_hitungan_kegagalan(client, fake_users, monkeypatch):
    config.RATE_LIMIT_LOGIN_MAX = 100
    import db
    inserted = []
    monkeypatch.setattr(db, "insert_alert", lambda *a, **kw: inserted.append(a))
    monkeypatch.setattr(ws_manager, "broadcast", lambda payload: None)

    fake_users["admin"] = {
        "username": "admin", "role": "admin",
        "password_hash": auth.hash_password("rahasia123"),
    }
    client.post("/api/login", json={"username": "admin", "password": "salah1"})
    client.post("/api/login", json={"username": "admin", "password": "salah2"})
    r = client.post("/api/login", json={"username": "admin", "password": "rahasia123"})
    assert r.status_code == 200

    # Hitungan sudah di-reset - butuh 3 kegagalan BARU lagi, bukan lanjut dari 2 tadi
    client.post("/api/login", json={"username": "admin", "password": "salah3"})
    client.post("/api/login", json={"username": "admin", "password": "salah4"})
    assert inserted == []


def test_username_kepanjangan_ditolak_pydantic(client):
    r = client.post("/api/login", json={"username": "a" * 101, "password": "x"})
    assert r.status_code == 422
