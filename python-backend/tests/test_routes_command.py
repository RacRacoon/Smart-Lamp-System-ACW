"""Test /api/lights/{device_id}/command - gerbang admin-only, validasi device_id
(nutup celah MQTT topic injection), dan rate limit admin_write."""
import config
import mqtt_ingest


def test_command_tanpa_token_403(client):
    r = client.post("/api/lights/L-101/command", json={"dim": 50})
    assert r.status_code == 403


def test_command_dim_di_luar_batas_400(client, admin_token):
    r = client.post("/api/lights/L-101/command", json={"dim": 150},
                     headers={"X-ACW-Token": admin_token})
    assert r.status_code == 400


def test_command_device_id_invalid_ditolak_sebelum_publish_mqtt(client, admin_token, monkeypatch):
    dipanggil = []
    monkeypatch.setattr(mqtt_ingest, "publish_dim_command", lambda *a: dipanggil.append(a))

    r = client.post("/api/lights/L+101/command", json={"dim": 50},
                     headers={"X-ACW-Token": admin_token})

    assert r.status_code == 400
    assert dipanggil == []  # publish_dim_command TIDAK BOLEH kepanggil buat id invalid


def test_command_device_id_sah_diteruskan_ke_mqtt(client, admin_token, monkeypatch):
    dipanggil = []
    monkeypatch.setattr(mqtt_ingest, "publish_dim_command", lambda *a: dipanggil.append(a))

    r = client.post("/api/lights/L-101/command", json={"dim": 50},
                     headers={"X-ACW-Token": admin_token})

    assert r.status_code == 200
    assert dipanggil == [("L-101", 50)]


def test_command_dibatasi_rate_limit_per_token(client, admin_token, monkeypatch):
    monkeypatch.setattr(mqtt_ingest, "publish_dim_command", lambda *a: None)
    config.RATE_LIMIT_ADMIN_WRITE_MAX = 2
    config.RATE_LIMIT_ADMIN_WRITE_WINDOW = 60

    codes = []
    for _ in range(4):
        r = client.post("/api/lights/L-101/command", json={"dim": 50},
                         headers={"X-ACW-Token": admin_token})
        codes.append(r.status_code)

    assert codes == [200, 200, 429, 429]


def test_mqtt_ingest_menolak_device_id_invalid_langsung():
    # Jaring KEDUA - lihat komentar di mqtt_ingest.publish_dim_command(). Endpoint HTTP
    # sudah menolak duluan (test di atas), tapi fungsi ini sendiri juga harus menolak
    # kalau suatu saat dipanggil dari jalur lain (mis. schedule publish).
    import pytest
    with pytest.raises(ValueError):
        mqtt_ingest.publish_dim_command("a/../b", 50)
