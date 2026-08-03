"""
Autentikasi & sesi. Menggantikan node "Handle Login" cs di node-red-flow-acw.json.

Hash baru pakai Argon2id (argon2-cffi) - pemenang Password Hashing Competition,
rekomendasi OWASP saat ini, lebih tahan brute-force GPU/ASIC dibanding scrypt.
Encoded string argon2 selalu mulai dengan "$argon2id$..." jadi bisa dibedakan
dari format lama tanpa kolom baru di DB.

Hash lama (dibuat sebelumnya lewat Node crypto.scryptSync, format 'salt_hex:hash_hex')
tetap bisa diverifikasi oleh needs_legacy_rehash()/verify_password() di bawah - salt
disimpan sebagai STRING HEX dan Node memperlakukan string itu sebagai UTF-8 saat
dipakai jadi salt scrypt (bukan di-decode dari hex jadi bytes mentah), makanya
_verify_legacy_scrypt() meniru itu persis: salt.encode('utf-8'), bukan bytes.fromhex(salt).
User dengan hash lama otomatis di-upgrade ke argon2id saat login berhasil
(lihat routes_auth.py) - tidak perlu migrasi manual.
"""
import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass
from typing import Optional

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHashError

import config

SCRYPT_N = 16384
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_MAXMEM = 32 * 1024 * 1024
SCRYPT_DKLEN = 64

# Parameter default argon2-cffi (time_cost=3, memory_cost=64MB, parallelism=4) sudah
# di atas rekomendasi minimum OWASP - dipakai apa adanya, tidak perlu di-tune manual.
_ph = PasswordHasher()


def hash_password(password: str) -> str:
    """Buat hash baru argon2id. Dipakai untuk user baru & auto-rehash user lama."""
    return _ph.hash(password)


def _verify_legacy_scrypt(password: str, stored_hash: str) -> bool:
    if not stored_hash or ":" not in stored_hash:
        return False
    salt, hash_hex = stored_hash.split(":", 1)
    try:
        expected = bytes.fromhex(hash_hex)
    except ValueError:
        return False
    derived = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt.encode("utf-8"),
        n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, maxmem=SCRYPT_MAXMEM, dklen=SCRYPT_DKLEN,
    )
    if len(derived) != len(expected):
        return False
    return hmac.compare_digest(derived, expected)  # perbandingan tahan timing-attack


def verify_password(password: str, stored_hash: str) -> bool:
    if not stored_hash:
        return False
    if stored_hash.startswith("$argon2"):
        try:
            return _ph.verify(stored_hash, password)
        except (VerifyMismatchError, InvalidHashError):
            return False
    return _verify_legacy_scrypt(password, stored_hash)


def is_legacy_hash(stored_hash: str) -> bool:
    """True kalau hash masih format scrypt lama - dipakai routes_auth.py buat auto-rehash."""
    return bool(stored_hash) and not stored_hash.startswith("$argon2")


@dataclass
class Session:
    role: str
    expires_at: float


# Sesi disimpan di memori proses (setara global.get('acwSessions') di Node-RED lama).
# Hilang kalau proses restart - itu sudah perilaku yang disepakati sebelumnya.
_sessions: dict[str, Session] = {}


def _prune_expired() -> None:
    now = time.time()
    expired = [t for t, s in _sessions.items() if s.expires_at < now]
    for t in expired:
        del _sessions[t]


def issue_session(role: str) -> str:
    _prune_expired()
    token = "tok_" + secrets.token_urlsafe(24)
    _sessions[token] = Session(role=role, expires_at=time.time() + config.SESSION_DURATION_HOURS * 3600)
    return token


def get_session(token: Optional[str]) -> Optional[Session]:
    if not token:
        return None
    session = _sessions.get(token)
    if not session:
        return None
    if session.expires_at < time.time():
        del _sessions[token]
        return None
    return session


def is_admin(token: Optional[str]) -> bool:
    session = get_session(token)
    return session is not None and session.role == "admin"
