import hashlib
import secrets
import unicodedata

from pwdlib import PasswordHash

password_hasher = PasswordHash.recommended()
_dummy_password_hash = password_hasher.hash("trainlab-invalid-user-dummy-password")


def normalize_username(username: str) -> str:
    return unicodedata.normalize("NFKC", username).strip().casefold()


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password: str, stored_hash: str) -> bool:
    return password_hasher.verify(password, stored_hash)


def perform_dummy_password_check(password: str) -> None:
    password_hasher.verify(password, _dummy_password_hash)


def new_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
