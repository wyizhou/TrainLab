"""Authenticated backup container primitives, independent of database I/O."""
from __future__ import annotations

from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MAGIC = b"TLFB"
VERSION = b"\x01"


def require_key(key: bytes | Any) -> bytes:
    secret = key() if callable(key) else key
    if not isinstance(secret, bytes) or len(secret) != 32:
        raise ValueError("backup_key_must_be_32_bytes")
    return secret


def encrypt_container(plaintext: bytes, key: bytes | Any, nonce: bytes) -> bytes:
    return MAGIC + VERSION + nonce + AESGCM(require_key(key)).encrypt(nonce, plaintext, MAGIC + VERSION)


def decrypt_container(payload: bytes, key: bytes | Any) -> bytes:
    if len(payload) < len(MAGIC) + 1 + 12 or payload[:4] != MAGIC or payload[4:5] != VERSION:
        raise ValueError("invalid_backup_container")
    return AESGCM(require_key(key)).decrypt(payload[5:17], payload[17:], MAGIC + VERSION)
