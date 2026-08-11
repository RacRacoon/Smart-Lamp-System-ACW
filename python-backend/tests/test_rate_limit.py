"""Test rate_limit.py - sliding window in-memory yang menahan brute-force login,
spam AI chat, dan spam endpoint publik/admin (ditambahkan sesi kerja sebelumnya)."""
import time

import rate_limit


def test_allow_sampai_limit_lalu_tolak():
    codes = [rate_limit.check("bucket-a", "1.2.3.4", 3, 60)[0] for _ in range(5)]
    assert codes == [True, True, True, False, False]


def test_bucket_beda_tidak_saling_pengaruh():
    # Jatah login habis tidak boleh ikut memblokir bucket lain (mis. "ai") - lihat
    # alasannya di rate_limit.check().
    for _ in range(3):
        rate_limit.check("login", "1.2.3.4", 3, 60)
    assert rate_limit.check("login", "1.2.3.4", 3, 60)[0] is False
    assert rate_limit.check("ai", "1.2.3.4", 3, 60)[0] is True


def test_key_beda_tidak_saling_pengaruh():
    # IP/token beda harus dapat jatah masing-masing, bukan jatah bersama.
    for _ in range(3):
        rate_limit.check("bucket-b", "ip-1", 3, 60)
    assert rate_limit.check("bucket-b", "ip-1", 3, 60)[0] is False
    assert rate_limit.check("bucket-b", "ip-2", 3, 60)[0] is True


def test_window_geser_buka_jatah_baru():
    window = 0.2  # detik, sengaja kecil biar test cepat
    assert rate_limit.check("bucket-c", "ip-3", 1, window)[0] is True
    assert rate_limit.check("bucket-c", "ip-3", 1, window)[0] is False
    time.sleep(window + 0.05)
    assert rate_limit.check("bucket-c", "ip-3", 1, window)[0] is True


def test_retry_after_positif_saat_ditolak():
    rate_limit.check("bucket-d", "ip-4", 1, 60)
    allowed, retry_after = rate_limit.check("bucket-d", "ip-4", 1, 60)
    assert allowed is False
    assert retry_after >= 1


def test_client_ip_default_ke_ip_koneksi(monkeypatch):
    import config
    monkeypatch.setattr(config, "TRUST_PROXY_HEADERS", False)

    class FakeRequest:
        headers = {"x-forwarded-for": "9.9.9.9"}
        client = type("C", (), {"host": "10.0.0.5"})()

    # TRUST_PROXY_HEADERS mati -> header klien harus DIABAIKAN, bukan dipakai buat
    # lolos rate limit (header itu gampang dipalsukan klien).
    assert rate_limit.client_ip(FakeRequest()) == "10.0.0.5"


def test_client_ip_pakai_entri_paling_kanan_saat_trust_proxy(monkeypatch):
    import config
    monkeypatch.setattr(config, "TRUST_PROXY_HEADERS", True)

    class FakeRequest:
        headers = {"x-forwarded-for": "1.2.3.4, 10.0.0.5"}
        client = type("C", (), {"host": "10.0.0.5"})()

    # Caddy nambahin IP peer asli ke ujung KANAN daftar - entri kiri "1.2.3.4" itu
    # yang bisa dikarang klien, harus diabaikan.
    assert rate_limit.client_ip(FakeRequest()) == "10.0.0.5"
