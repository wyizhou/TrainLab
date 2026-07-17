import hashlib
import os
import stat
import uuid
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import BinaryIO

from fastapi import UploadFile


class StorageError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class StagedUpload:
    storage_key: str
    path: Path
    sha256: str
    size_bytes: int


@dataclass(frozen=True)
class OpenedPrivateFile:
    handle: BinaryIO
    size_bytes: int


class PrivateActivityStorage:
    def __init__(self, root: Path) -> None:
        try:
            self.root = root.expanduser().resolve()
        except (OSError, RuntimeError):
            raise StorageError("private_storage_unavailable", "私有文件存储不可用") from None
        if self.root.parent == self.root:
            raise StorageError("private_storage_unavailable", "私有文件存储不可用")

    def path_for_key(self, storage_key: str, expected_user_id: uuid.UUID) -> Path:
        relative = PurePosixPath(storage_key)
        if relative.is_absolute() or len(relative.parts) != 2:
            raise StorageError("invalid_storage_key", "私有文件路径无效")
        try:
            user_id = uuid.UUID(relative.parts[0])
            import_id = uuid.UUID(Path(relative.parts[1]).stem)
        except ValueError:
            raise StorageError("invalid_storage_key", "私有文件路径无效") from None
        if relative.suffix.lower() != ".fit":
            raise StorageError("invalid_storage_key", "私有文件路径无效")
        if user_id != expected_user_id:
            raise StorageError("invalid_storage_key", "私有文件路径无效")
        user_root = self.root / str(user_id)
        candidate = user_root / f"{import_id}.fit"
        try:
            candidate.relative_to(user_root)
        except ValueError:
            raise StorageError("invalid_storage_key", "私有文件路径越界") from None
        return candidate

    async def stage(
        self,
        upload: UploadFile,
        user_id: uuid.UUID,
        import_id: uuid.UUID,
        max_bytes: int,
    ) -> StagedUpload:
        storage_key = f"{user_id}/{import_id}.fit"
        path = self.path_for_key(storage_key, user_id)
        root_descriptor: int | None = None
        user_descriptor: int | None = None
        file_descriptor: int | None = None
        created = False
        directory_flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        directory_flags |= getattr(os, "O_DIRECTORY", 0)
        digest = hashlib.sha256()
        size = 0
        try:
            self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
            root_descriptor = os.open(self.root, directory_flags)
            os.fchmod(root_descriptor, 0o700)
            with suppress(FileExistsError):
                os.mkdir(str(user_id), 0o700, dir_fd=root_descriptor)
            user_descriptor = os.open(str(user_id), directory_flags, dir_fd=root_descriptor)
            os.fchmod(user_descriptor, 0o700)
            file_flags = (
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0)
            )
            file_descriptor = os.open(
                path.name,
                file_flags,
                0o600,
                dir_fd=user_descriptor,
            )
            created = True
            os.fchmod(file_descriptor, 0o600)
            target = os.fdopen(file_descriptor, "wb")
            file_descriptor = None
            with target:
                while chunk := await upload.read(1024 * 1024):
                    size += len(chunk)
                    if size > max_bytes:
                        raise StorageError("fit_file_too_large", "FIT 文件超过大小上限")
                    digest.update(chunk)
                    target.write(chunk)
                target.flush()
                os.fsync(target.fileno())
            if size == 0:
                raise StorageError("fit_file_empty", "FIT 文件为空")
        except StorageError:
            if created and user_descriptor is not None:
                with suppress(OSError):
                    os.unlink(path.name, dir_fd=user_descriptor)
            raise
        except Exception:
            if created and user_descriptor is not None:
                with suppress(OSError):
                    os.unlink(path.name, dir_fd=user_descriptor)
            raise StorageError("private_storage_unavailable", "私有文件存储不可用") from None
        finally:
            for descriptor in (file_descriptor, user_descriptor, root_descriptor):
                if descriptor is not None:
                    with suppress(OSError):
                        os.close(descriptor)
        return StagedUpload(
            storage_key=storage_key,
            path=path,
            sha256=digest.hexdigest(),
            size_bytes=size,
        )

    def remove(self, storage_key: str, expected_user_id: uuid.UUID) -> None:
        path = self.path_for_key(storage_key, expected_user_id)
        root_descriptor: int | None = None
        user_descriptor: int | None = None
        directory_flags = (
            os.O_RDONLY
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_DIRECTORY", 0)
        )
        try:
            root_descriptor = os.open(self.root, directory_flags)
            user_descriptor = os.open(
                str(expected_user_id), directory_flags, dir_fd=root_descriptor
            )
            with suppress(FileNotFoundError):
                os.unlink(path.name, dir_fd=user_descriptor)
        except FileNotFoundError:
            return
        except (OSError, RuntimeError):
            raise StorageError("private_storage_unavailable", "私有文件存储不可用") from None
        finally:
            for descriptor in (user_descriptor, root_descriptor):
                if descriptor is not None:
                    with suppress(OSError):
                        os.close(descriptor)

    def open_for_read(self, storage_key: str, expected_user_id: uuid.UUID) -> OpenedPrivateFile:
        """Open a regular owner file before the HTTP response starts streaming.

        Keeping the descriptor open pins the verified file across unlink/replace
        races. O_NOFOLLOW prevents a final-component symlink swap, and all path-
        bearing operating-system errors are converted to a context-free domain
        error before they can reach request logging.
        """

        path = self.path_for_key(storage_key, expected_user_id)
        root_descriptor: int | None = None
        user_descriptor: int | None = None
        file_descriptor: int | None = None
        directory_flags = (
            os.O_RDONLY
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_DIRECTORY", 0)
        )
        try:
            root_descriptor = os.open(self.root, directory_flags)
        except (OSError, RuntimeError):
            raise StorageError("private_storage_unavailable", "私有文件存储不可用") from None
        try:
            user_descriptor = os.open(
                str(expected_user_id), directory_flags, dir_fd=root_descriptor
            )
            file_flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
            file_descriptor = os.open(path.name, file_flags, dir_fd=user_descriptor)
            file_stat = os.fstat(file_descriptor)
            if not stat.S_ISREG(file_stat.st_mode):
                raise OSError("not a regular file")
            handle = os.fdopen(file_descriptor, "rb")
            file_descriptor = None
            return OpenedPrivateFile(handle=handle, size_bytes=file_stat.st_size)
        except (OSError, RuntimeError):
            raise StorageError("raw_file_unavailable", "原始 FIT 文件不可用") from None
        finally:
            for descriptor in (file_descriptor, user_descriptor, root_descriptor):
                if descriptor is not None:
                    with suppress(OSError):
                        os.close(descriptor)
