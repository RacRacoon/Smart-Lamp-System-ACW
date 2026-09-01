"""
POST /api/login. Setara dengan node "Prepare Login Query" -> "Get User By Username" ->
"Verify Password & Issue Session" di node-red-flow-acw.json, sekarang jadi kode Python
biasa (tidak perlu lagi akal-akalan functionGlobalContext buat akses crypto).
"""
import logging

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field

import alerts
import auth
import config
import db
import rate_limit
import ws_manager

logger = logging.getLogger("acw.routes.auth")
router = APIRouter(prefix="/api", tags=["auth"])

# Kelipatan kegagalan berturut-turut yang memicu alert (3, 6, 9, ...) - lihat
# auth.record_login_failure() & alerts.repeated_login_failure_alert().
REPEATED_FAILURE_ALERT_EVERY = 3


class LoginRequest(BaseModel):
    # max_length gerbang sumber: tanpa ini, username/password raksasa (klien bisa
    # kirim berapa saja, Pydantic str polos tidak batasi) ikut disimpan ke pesan alert
    # (lihat alerts.repeated_login_failure_alert()) lalu disiarkan WS ke semua
    # dashboard tiap gagal login kelipatan 3 - vektor bandwidth/memori murah kalau
    # dibiarkan tak terbatas. 100/200 longgar buat pemakaian normal, cuma memagari
    # kasus ekstrem.
    username: str = Field(default="", max_length=100)
    password: str = Field(default="", max_length=200)


class LoginResponse(BaseModel):
    role: str
    token: str


class LogoutResponse(BaseModel):
    ok: bool


@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest, request: Request):
    # Dibatasi per-IP SEBELUM query database: tanpa ini password admin bisa ditebak
    # secepat jaringan mengizinkan. Kunci rate limit-nya IP, bukan username - kalau
    # dikunci per-username, penyerang justru bisa memakainya buat mengunci akun admin
    # sungguhan dari luar (denial of service ke pemilik akun yang sah).
    allowed, retry_after = rate_limit.check(
        "login", rate_limit.client_ip(request),
        config.RATE_LIMIT_LOGIN_MAX, config.RATE_LIMIT_LOGIN_WINDOW,
    )
    if not allowed:
        raise HTTPException(
            status_code=429,
            # retry_after_seconds dipisah dari teks pesan - front-end butuh angka murni
            # buat hitung mundur tombol, bukan cuma pesannya (lihat handleLogin di
            # script.js). Teks tetap dikirim juga buat yang JS-nya gagal jalan.
            detail={
                "error": f"Terlalu banyak percobaan login. Coba lagi dalam {retry_after} detik.",
                "retry_after_seconds": retry_after,
            },
        )

    username = body.username.strip()
    password = body.password

    if not username or not password:
        raise HTTPException(status_code=400, detail={"error": "Username dan password wajib diisi"})

    user = db.get_user_by_username(username)

    # verify_password() SELALU dipanggil, walau username tidak ketemu (pakai
    # auth.DUMMY_HASH) - kalau di-skip lewat "not user or ...", waktu respons jadi beda
    # jauh antara username tidak ada (instan) vs username ada tapi password salah
    # (nunggu argon2id selesai hashing). Pesan errornya sudah sama-sama generik dari
    # dulu, tapi tanpa ini timing-nya sendiri jadi celah enumerasi username.
    password_hash = user["password_hash"] if user else auth.DUMMY_HASH
    password_ok = auth.verify_password(password, password_hash)
    if not user or not password_ok:
        failures = auth.record_login_failure(username)
        # Kelipatan 3 (3, 6, 9, ...), bukan cuma sekali di kegagalan ke-3 - kalau
        # percobaannya terus, admin yang online tetap dapat sinyal berulang, bukan
        # cuma sekali lalu dianggap selesai.
        if failures % REPEATED_FAILURE_ALERT_EVERY == 0:
            _notify_repeated_login_failure(username, failures, rate_limit.client_ip(request))
        raise HTTPException(status_code=401, detail={"error": "Username atau password salah"})

    auth.record_login_success(username)

    # Login berhasil pakai hash lama (scrypt) -> upgrade diam-diam ke argon2id.
    # Password plaintext cuma ada sebentar di request ini, jadi ini satu-satunya
    # kesempatan buat rehash tanpa minta user ganti password manual.
    if auth.is_legacy_hash(user["password_hash"]):
        db.update_password_hash(username, auth.hash_password(password))

    token = auth.issue_session(user["role"])
    return {"role": user["role"], "token": token}


def _notify_repeated_login_failure(username: str, failures: int, client_ip: str) -> None:
    """Simpan + siarkan alert kegagalan login berulang - pola PERSIS sama dengan
    alert perangkat di mqtt_ingest.py (bangun dict lewat alerts.py, simpan lewat
    db.insert_alert, siarkan lewat ws_manager.broadcast). Kegagalan simpan/siar
    TIDAK BOLEH gagalkan response 401 ke pemanggil - itu kenapa dibungkus try/except
    di sini, bukan dibiarkan menjalar ke login()."""
    alert = alerts.repeated_login_failure_alert(username, failures, client_ip)
    try:
        db.insert_alert(
            None, alert["level"], alert["title"], alert["message"],
            0, 0, 0, alert["threshold_info"],
        )
    except Exception:
        logger.exception("Gagal simpan alert login gagal berulang buat '%s'", username)

    # Sengaja TIDAK pakai key "id" - itu trigger dashboard mendaftarkan "device" baru
    # (lihat socket.onmessage di script.js, sama seperti alert perangkat tak dikenal).
    ws_manager.broadcast({
        "alert": True,
        "device_id": username,
        "severity": "critical",
        "alertType": alert["alertType"],
        "level": alert["level"],
        "title": alert["title"],
        "message": alert["message"],
    })


@router.post("/logout", response_model=LogoutResponse)
def logout(x_acw_token: str | None = Header(default=None, alias="X-ACW-Token")):
    # Cabut token di server, bukan cuma hapus di browser - lihat catatan di
    # auth.invalidate_session(). Selalu 200 walau token sudah tidak valid/kosong,
    # supaya klien tidak perlu bedakan "berhasil logout" vs "sesi sudah mati sendiri".
    auth.invalidate_session(x_acw_token)
    return {"ok": True}
