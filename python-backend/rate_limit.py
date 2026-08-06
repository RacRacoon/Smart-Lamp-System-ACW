"""
Rate limiter sliding-window in-memory. Disimpan di memori proses, sama seperti sesi
login di auth.py - hilang saat restart, dan tidak dibagi antar instance kalau nanti
backend di-scale lebih dari satu proses. Untuk skala dasbor ini (satu proses, satu
server) itu sudah cukup; kalau nanti multi-instance, penggantinya Redis.

Alasan ada: /api/login dan /api/chat dua-duanya publik tanpa login.
- /api/login tanpa batas = password admin bisa ditebak brute-force sepuasnya.
- /api/chat tiap panggilan menembak API Gemini. Kuota tier gratisnya ketat (lihat
  komentar GEMINI_MODEL di config.py), jadi satu orang yang spam endpoint ini bisa
  menghabiskan kuota harian dan mematikan fitur AI buat semua pengguna asli.
"""
import logging
import threading
import time
from collections import deque

import config

logger = logging.getLogger("acw.rate_limit")

# Batas jumlah key yang dilacak sekaligus. Tiap IP unik bikin satu entri, jadi tanpa
# batas ini pengirim request dari IP acak (atau header X-Forwarded-For yang dipalsukan
# saat TRUST_PROXY_HEADERS aktif) bisa menggelembungkan memori proses terus-menerus.
MAX_TRACKED_KEYS = 10000

_lock = threading.Lock()
_hits: dict[tuple[str, str], deque[float]] = {}


def _prune_locked(now: float) -> None:
    """Buang key yang semua timestamp-nya sudah kedaluwarsa. Dipanggil hanya saat
    jumlah key mendekati batas, bukan tiap request - menyapu seluruh dict di jalur
    panas justru bikin endpoint-nya sendiri lambat saat ramai."""
    stale = [k for k, dq in _hits.items() if not dq or now - dq[-1] > 3600]
    for k in stale:
        del _hits[k]
    if len(_hits) >= MAX_TRACKED_KEYS:
        # Masih penuh setelah disapu - buang yang paling lama tidak aktif.
        for k in sorted(_hits, key=lambda k: _hits[k][-1])[: len(_hits) // 2]:
            del _hits[k]
        logger.warning("Tabel rate limit penuh, entri paling lama tidak aktif dibuang")


def check(bucket: str, client_id: str, limit: int, window_seconds: int) -> tuple[bool, int]:
    """True kalau request boleh lanjut. Return (diizinkan, detik_sampai_boleh_lagi).

    `bucket` memisahkan kuota per endpoint - jatah login habis tidak ikut memblokir
    chat, dan sebaliknya.
    """
    now = time.time()
    key = (bucket, client_id)

    with _lock:
        if len(_hits) >= MAX_TRACKED_KEYS:
            _prune_locked(now)

        dq = _hits.get(key)
        if dq is None:
            dq = deque()
            _hits[key] = dq

        cutoff = now - window_seconds
        while dq and dq[0] <= cutoff:
            dq.popleft()

        if len(dq) >= limit:
            retry_after = int(dq[0] + window_seconds - now) + 1
            return False, max(retry_after, 1)

        dq.append(now)
        return True, 0


def client_ip(request) -> str:
    """IP pemanggil, dipakai jadi key rate limit.

    X-Forwarded-For HANYA dibaca kalau TRUST_PROXY_HEADERS diaktifkan, karena header itu
    dikirim klien dan gampang dipalsukan - kalau dipercaya tanpa syarat, penyerang cukup
    mengganti-ganti isinya tiap request buat dapat jatah baru terus dan rate limit ini
    jadi tidak ada artinya.

    Saat aktif, yang diambil entri PALING KANAN, bukan paling kiri: Caddy MENAMBAHKAN IP
    peer sungguhan ke ujung daftar, jadi kalau klien mengirim "1.2.3.4" palsu hasilnya
    jadi "1.2.3.4, <ip-asli>". Entri paling kiri itu justru yang dikarang klien; yang
    paling kanan diisi proxy kita sendiri. Ini hanya benar untuk SATU hop proxy tepercaya
    (Caddyfile di repo ini) - kalau nanti ada CDN di depan Caddy, jumlah hop yang
    dilewati harus dihitung ulang.
    """
    if config.TRUST_PROXY_HEADERS:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            parts = [p.strip() for p in forwarded.split(",") if p.strip()]
            if parts:
                return parts[-1]

    return request.client.host if request.client else "unknown"
