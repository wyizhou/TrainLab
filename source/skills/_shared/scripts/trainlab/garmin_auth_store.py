from __future__ import annotations

import base64
import fcntl
import hashlib
import json
import os
import re
import stat
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from trainlab.contracts.errors import ErrorCode
from trainlab.contracts.paths import GARMIN_CONFIG_PATH
from trainlab.garmin_auth_sdk import GarminSDK, SDKFactory
from trainlab.garmin_auth_types import GarminAuthError

_LOCKS_GUARD = threading.Lock()
_LOCKS: dict[str, threading.Lock] = {}
_TOKEN_FILES = ("oauth1_token.json", "oauth2_token.json")
_GENERATIONS = GARMIN_CONFIG_PATH.parent / "garmin-tokenstore"


@dataclass(frozen=True, repr=False)
class AuthSnapshot:
    revision: str
    raw: bytes | None = field(repr=False)
    config: dict[str, Any] = field(repr=False)


class GarminAuthStore:
    def __init__(self, instance_root: Path) -> None:
        self._input_root = instance_root.absolute()
        self._held = False

    def _root(self) -> Path:
        if self._input_root.is_symlink():
            raise GarminAuthError(ErrorCode.CONFIG_UNAVAILABLE, "unsafe_auth_path")
        return self._input_root.resolve()

    def _path(self, relative: Path, *, directory: bool = False, create: bool = False) -> Path:
        if relative.is_absolute() or ".." in relative.parts:
            raise GarminAuthError(ErrorCode.CONFIG_UNAVAILABLE, "unsafe_auth_path")
        root = self._root()
        if create:
            root.mkdir(mode=0o700, parents=True, exist_ok=True)
        path = root
        for index, part in enumerate(relative.parts):
            path = path / part
            is_dir = index < len(relative.parts) - 1 or directory
            try:
                info = path.lstat()
            except FileNotFoundError:
                if create and is_dir:
                    path.mkdir(mode=0o700)
                    info = path.lstat()
                else:
                    continue
            if stat.S_ISLNK(info.st_mode) or info.st_uid != os.getuid() or (is_dir and not stat.S_ISDIR(info.st_mode)) or (not is_dir and (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1)):
                raise GarminAuthError(ErrorCode.CONFIG_UNAVAILABLE, "unsafe_auth_path")
            if create and is_dir:
                path.chmod(0o700)
        return path

    @contextmanager
    def locked(self) -> Iterator[None]:
        key = str(self._root())
        with _LOCKS_GUARD:
            lock = _LOCKS.setdefault(key, threading.Lock())
        if not lock.acquire(blocking=False):
            raise GarminAuthError(ErrorCode.RUN_BUSY, "auth_lock_busy")
        fd: int | None = None
        try:
            path = self._path(GARMIN_CONFIG_PATH.parent / ".garmin-auth.lock", create=True)
            fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid():
                raise GarminAuthError(ErrorCode.CONFIG_UNAVAILABLE, "unsafe_auth_path")
            os.fchmod(fd, 0o600)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise GarminAuthError(ErrorCode.RUN_BUSY, "auth_lock_busy") from None
            self._held = True
            yield
        except OSError:
            raise GarminAuthError(ErrorCode.EXTERNAL_SERVICE_FAILED, "auth_storage_failed") from None
        finally:
            self._held = False
            if fd is not None:
                os.close(fd)
            lock.release()

    def _require_lock(self) -> None:
        if not self._held:
            raise RuntimeError("Authentication storage requires its owner lock")

    def snapshot(self) -> AuthSnapshot:
        self._require_lock()
        path = self._path(GARMIN_CONFIG_PATH)
        try:
            raw = self._read(path)
        except FileNotFoundError:
            return AuthSnapshot("missing", None, {})
        try:
            config = json.loads(raw)
            if not isinstance(config, dict):
                raise TypeError
        except (ValueError, TypeError, UnicodeError):
            raise GarminAuthError(ErrorCode.DATA_INVALID, "config_format_invalid") from None
        return AuthSnapshot(hashlib.sha256(raw).hexdigest(), raw, config)

    def load(self, snapshot: AuthSnapshot, factory: SDKFactory) -> GarminSDK:
        self._require_lock()
        config = snapshot.config
        if snapshot.raw is None:
            raise GarminAuthError(ErrorCode.AUTH_REFRESH_REQUIRED, "login_required")
        if any(key.startswith("di_") for key in config):
            raise GarminAuthError(ErrorCode.AUTH_REFRESH_REQUIRED, "legacy_auth_requires_login")
        is_cn = config.get("is_cn", False)
        if type(is_cn) is not bool:
            raise GarminAuthError(ErrorCode.DATA_INVALID, "config_format_invalid")
        if "version" in config and (type(config["version"]) is not int or config["version"] != 1):
            raise GarminAuthError(ErrorCode.DATA_INVALID, "config_version_invalid")
        directory: Path | None
        if config.get("version") == 1:
            generation = config.get("generation")
            if config.get("backend") != "garminconnect" or not isinstance(generation, str) or not re.fullmatch(r"g-[a-f0-9]{32}", generation):
                raise GarminAuthError(ErrorCode.DATA_INVALID, "config_format_invalid")
            if config.get("tokenstore") != (_GENERATIONS / generation).as_posix():
                raise GarminAuthError(ErrorCode.DATA_INVALID, "config_format_invalid")
            directory = self._token_directory(Path(config["tokenstore"]))
            encoded = None
        else:
            value = config.get("garth_tokenstore") or config.get("tokenstore")
            if not isinstance(value, str) or not value:
                raise GarminAuthError(ErrorCode.AUTH_REFRESH_REQUIRED, "legacy_auth_requires_login")
            encoded = self._encoded(value)
            directory = None if encoded else self._token_directory(self._legacy_relative(value))
        sdk = factory(is_cn=is_cn)
        try:
            if encoded:
                sdk.loads(encoded)
            else:
                assert directory is not None
                sdk.load(directory)
            return sdk
        except BaseException:
            sdk.close()
            raise

    def _legacy_relative(self, value: str) -> Path:
        path = Path(value)
        if path.is_absolute():
            try:
                path = path.relative_to(self._root())
            except ValueError:
                raise GarminAuthError(ErrorCode.CONFIG_UNAVAILABLE, "legacy_path_outside_instance") from None
        return path

    def _encoded(self, value: str) -> str | None:
        try:
            decoded = json.loads(base64.b64decode(value, validate=True))
        except (ValueError, UnicodeError):
            return None
        if not isinstance(decoded, list) or len(decoded) != 2 or not all(isinstance(item, dict) for item in decoded):
            raise GarminAuthError(ErrorCode.DATA_INVALID, "token_format_invalid")
        return value

    def _token_directory(self, relative: Path) -> Path:
        directory = self._path(relative, directory=True)
        for filename in _TOKEN_FILES:
            path = self._path(relative / filename)
            if not path.is_file():
                raise GarminAuthError(ErrorCode.DATA_INVALID, "token_pair_incomplete")
        return directory

    def commit(self, sdk: GarminSDK, expected: str, factory: SDKFactory) -> str:
        self._require_lock()
        old = self.snapshot()
        if old.revision != expected:
            raise GarminAuthError(ErrorCode.SOURCE_CONFLICT, "auth_generation_changed")
        sdk.fingerprint()
        generation = "g-" + uuid.uuid4().hex
        relative = _GENERATIONS / generation
        directory = self._path(relative, directory=True, create=True)
        for name in _TOKEN_FILES:
            self._write_new(directory / name, b"")
        sdk.dump(directory)
        for name in _TOKEN_FILES:
            path = self._path(relative / name)
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            try:
                os.fchmod(fd, 0o600)
                os.fsync(fd)
            finally:
                os.close(fd)
        check = factory(is_cn=sdk.is_cn)
        try:
            check.load(directory)
            if check.fingerprint() != sdk.fingerprint():
                raise GarminAuthError(ErrorCode.DATA_INVALID, "token_roundtrip_failed")
        finally:
            check.close()
        self._fsync(directory)
        self._fsync(directory.parent)
        if old.raw is not None:
            backup = self._path(GARMIN_CONFIG_PATH.parent / ("garmin-backup-" + old.revision + ".json"))
            if backup.exists():
                if self._read(backup) != old.raw:
                    raise GarminAuthError(ErrorCode.DATA_INVALID, "backup_conflict")
                backup.chmod(0o600)
            else:
                self._write_new(backup, old.raw)
            self._fsync(backup.parent)
        config = {"version": 1, "backend": "garminconnect", "is_cn": sdk.is_cn,
                  "generation": generation, "tokenstore": relative.as_posix()}
        raw = (json.dumps(config, sort_keys=True) + "\n").encode()
        target = self._path(GARMIN_CONFIG_PATH)
        temp = target.with_name(".garmin-" + uuid.uuid4().hex + ".tmp")
        rollback = target.with_name(".garmin-rollback-" + uuid.uuid4().hex + ".tmp")
        replaced = False
        try:
            self._write_new(temp, raw)
            if old.raw is not None:
                self._write_new(rollback, old.raw)
            self._fsync(temp.parent)
            os.replace(temp, target)
            replaced = True
            self._fsync(target.parent)
        except OSError:
            if replaced:
                if old.raw is None:
                    target.unlink()
                else:
                    os.replace(rollback, target)
                self._fsync(target.parent)
            raise
        finally:
            temp.unlink(missing_ok=True)
            rollback.unlink(missing_ok=True)
        return hashlib.sha256(raw).hexdigest()

    @staticmethod
    def _read(path: Path) -> bytes:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, "rb") as stream:
            return stream.read()

    @staticmethod
    def _write_new(path: Path, raw: bytes) -> None:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())

    @staticmethod
    def _fsync(path: Path) -> None:
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
