"""
Autentikasi & sesi. Menggantikan node "Handle Login" cs di node-red-flow-acw.json.

Detail penting: password_hash yang sudah ada di tabel users (dibuat sebelumnya lewat
Node crypto.scryptSync) menyimpan salt sebagai STRING HEX, dan Node memperlakukan string
itu sebagai UTF-8 saat dipakai jadi salt scrypt (bukan di-decode dari hex jadi bytes
mentah). Supaya hash lama tetap valid, verifikasi & pembuatan hash baru di sini SENGAJA
meniru perilaku itu persis: salt.encode('utf-8'), bukan bytes.fromhex(salt).
Sudah diverifikasi manual cocok dengan hash 'admin123' yang sudah tersimpan di DB.
"""
import hashlib
import hmac
import os
import secrets
import time
from dataclasses import dataclass
from typing import Optional

import config

SCRYPT_N = 16384
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_MAXMEM = 32 * 1024 * 1024
SCRYPT_DKLEN = 64


def hash_password(password: str) -> str:
    """Buat hash baru dengan salt acak. Format tersimpan: 'salt_hex:hash_hex'."""
    salt = secrets.token_hex(16)
    derived = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt.encode("utf-8"),
        n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, maxmem=SCRYPT_MAXMEM, dklen=SCRYPT_DKLEN,
    )
    return f"{salt}:{derived.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
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
