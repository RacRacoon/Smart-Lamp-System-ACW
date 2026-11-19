"""Test /api/change-password.

Yang dijaga di sini: endpoint ini hanya menyentuh akun pemilik token, menolak
password lama yang salah, dan mencabut sesi lain milik akun yang sama.
"""
import auth
import config


def test_tanpa_token_401(client):
    r = client.post("/api/change-password",
                    json={"current_password": "a", "new_password": "panjang123"})
    assert r.status_code == 401


def test_password_lama_salah_403(client, admin_token):
    r = client.post("/api/change-password",
                    json={"current_password": "bukan-ini", "new_password": "panjang123"},
                    headers={"X-ACW-Token": admin_token})
    assert r.status_code == 403


def test_password_baru_terlalu_pendek_400(client, admin_token):
    r = client.post("/api/change-password",
                    json={"current_password": "admin-secret-123", "new_password": "pendek"},
                    headers={"X-ACW-Token": admin_token})
    assert r.status_code == 400


def test_password_baru_sama_dengan_lama_400(client, admin_token):
    r = client.post("/api/change-password",
                    json={"current_password": "admin-secret-123",
                          "new_password": "admin-secret-123"},
                    headers={"X-ACW-Token": admin_token})
    assert r.status_code == 400


def test_berhasil_mengubah_hash_di_database(client, admin_token, fake_users):
    hash_lama = fake_users["admin"]["password_hash"]

    r = client.post("/api/change-password",
                    json={"current_password": "admin-secret-123",
                          "new_password": "rahasia-baru-123"},
                    headers={"X-ACW-Token": admin_token})

    assert r.status_code == 200
    assert fake_users["admin"]["password_hash"] != hash_lama
    assert auth.verify_password("rahasia-baru-123", fake_users["admin"]["password_hash"])


def test_sesi_lain_dicabut_tapi_sesi_sendiri_tetap_hidup(client, admin_token, fake_users):
    sesi_lain = auth.issue_session("admin", "admin")

    r = client.post("/api/change-password",
                    json={"current_password": "admin-secret-123",
                          "new_password": "rahasia-baru-123"},
                    headers={"X-ACW-Token": admin_token})

    assert r.status_code == 200
    assert r.json()["sessions_revoked"] == 1
    assert auth.get_session(sesi_lain) is None
    assert auth.get_session(admin_token) is not None


def test_hanya_menyentuh_akun_pemilik_token(client, fake_users):
    """Akun lain tidak boleh ikut berubah, bahkan kalau usernamenya dikirim."""
    fake_users["monitoring"] = {
        "username": "monitoring",
        "role": "user",
        "password_hash": auth.hash_password("monitoring-lama-123"),
    }
    fake_users["admin"] = {
        "username": "admin",
        "role": "admin",
        "password_hash": auth.hash_password("admin-secret-123"),
    }
    hash_admin = fake_users["admin"]["password_hash"]
    token = auth.issue_session("monitoring", "user")

    r = client.post("/api/change-password",
                    json={"current_password": "monitoring-lama-123",
                          "new_password": "monitoring-baru-123",
                          "username": "admin"},
                    headers={"X-ACW-Token": token})

    assert r.status_code == 200
    assert fake_users["admin"]["password_hash"] == hash_admin
    assert auth.verify_password("monitoring-baru-123",
                                fake_users["monitoring"]["password_hash"])


def test_dibatasi_rate_limit_per_ip(client, admin_token):
    config.RATE_LIMIT_LOGIN_MAX = 2
    config.RATE_LIMIT_LOGIN_WINDOW = 60

    codes = []
    for _ in range(4):
        r = client.post("/api/change-password",
                        json={"current_password": "salah", "new_password": "panjang123"},
                        headers={"X-ACW-Token": admin_token})
        codes.append(r.status_code)

    assert codes == [403, 403, 429, 429]
