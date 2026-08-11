"""Test config.is_valid_device_id() - gerbang yang menutup dua celah beda: XSS
tersimpan lewat device_id (commit 01e8a3b) dan MQTT topic injection lewat device_id
di endpoint command/schedule (sesi kerja sebelumnya)."""
import config


def test_device_id_sah_diterima():
    for ok in ["L-101", "L_101", "L.101", "a", "A" * 64, "device123"]:
        assert config.is_valid_device_id(ok) is True, ok


def test_device_id_kosong_ditolak():
    assert config.is_valid_device_id("") is False
    assert config.is_valid_device_id(None) is False


def test_device_id_kepanjangan_ditolak():
    assert config.is_valid_device_id("a" * 65) is False


def test_device_id_xss_payload_ditolak():
    # Payload yang sama semangatnya dengan yang ditutup commit 01e8a3b (XSS lewat
    # innerHTML alert) - device_id yang bawa markup tidak boleh lolos gerbang bentuk.
    payloads = [
        "<script>alert(1)</script>",
        "<img src=x onerror=alert(1)>",
        "\"><svg onload=alert(1)>",
    ]
    for p in payloads:
        assert config.is_valid_device_id(p) is False, p


def test_device_id_mqtt_topic_injection_ditolak():
    # "/" ubah topic tujuan publish, "+"/"#" wildcard MQTT - dua-duanya harus ditolak
    # supaya routes_command.py/mqtt_ingest.py tidak publish ke topic di luar
    # "iot/lights/<id>/command" yang dimaksud.
    payloads = ["L+101", "L#101", "a/../b", "iot/lights/+/command", "a/b/c"]
    for p in payloads:
        assert config.is_valid_device_id(p) is False, p
