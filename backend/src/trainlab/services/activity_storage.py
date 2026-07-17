import hashlib
import os
import stat
import uuid
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
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
    isolated: bool = False


@dataclass(frozen=True)
class GeneratedPrivateFile:
    user_id: uuid.UUID
    filename: str
    storage_key: str | None
    size_bytes: int
    modified_at: datetime
    isolated: bool


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
        return await self._stage(upload, user_id, import_id, max_bytes, isolated=False)

    async def stage_isolated(
        self,
        upload: UploadFile,
        user_id: uuid.UUID,
        import_id: uuid.UUID,
        max_bytes: int,
    ) -> StagedUpload:
        return await self._stage(upload, user_id, import_id, max_bytes, isolated=True)

    async def _stage(
        self,
        upload: UploadFile,
        user_id: uuid.UUID,
        import_id: uuid.UUID,
        max_bytes: int,
        *,
        isolated: bool,
    ) -> StagedUpload:
        storage_key = f"{user_id}/{import_id}.fit"
        final_path = self.path_for_key(storage_key, user_id)
        path = final_path.parent / ".staging" / f"{import_id}.fit.part" if isolated else final_path
        root_descriptor: int | None = None
        user_descriptor: int | None = None
        staging_descriptor: int | None = None
        target_descriptor: int | None = None
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
            target_descriptor = user_descriptor
            if isolated:
                with suppress(FileExistsError):
                    os.mkdir(".staging", 0o700, dir_fd=user_descriptor)
                staging_descriptor = os.open(".staging", directory_flags, dir_fd=user_descriptor)
                os.fchmod(staging_descriptor, 0o700)
                target_descriptor = staging_descriptor
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
                dir_fd=target_descriptor,
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
            if created and target_descriptor is not None:
                with suppress(OSError):
                    os.unlink(path.name, dir_fd=target_descriptor)
            raise
        except Exception:
            if created and target_descriptor is not None:
                with suppress(OSError):
                    os.unlink(path.name, dir_fd=target_descriptor)
            raise StorageError("private_storage_unavailable", "私有文件存储不可用") from None
        finally:
            for descriptor in (
                file_descriptor,
                staging_descriptor,
                user_descriptor,
                root_descriptor,
            ):
                if descriptor is not None:
                    with suppress(OSError):
                        os.close(descriptor)
        return StagedUpload(
            storage_key=storage_key,
            path=path,
            sha256=digest.hexdigest(),
            size_bytes=size,
            isolated=isolated,
        )

    def promote(self, staged: StagedUpload, expected_user_id: uuid.UUID) -> None:
        if not staged.isolated:
            raise StorageError("invalid_staged_upload", "暂存文件状态无效")
        final_path = self.path_for_key(staged.storage_key, expected_user_id)
        expected_staged_path = final_path.parent / ".staging" / f"{final_path.stem}.fit.part"
        if staged.path != expected_staged_path:
            raise StorageError("invalid_staged_upload", "暂存文件状态无效")
        root_descriptor: int | None = None
        user_descriptor: int | None = None
        staging_descriptor: int | None = None
        final_link_created = False
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
            staging_descriptor = os.open(".staging", directory_flags, dir_fd=user_descriptor)
            os.link(
                staged.path.name,
                final_path.name,
                src_dir_fd=staging_descriptor,
                dst_dir_fd=user_descriptor,
                follow_symlinks=False,
            )
            final_link_created = True
            os.unlink(staged.path.name, dir_fd=staging_descriptor)
            os.fsync(user_descriptor)
        except (OSError, RuntimeError):
            if final_link_created and user_descriptor is not None:
                with suppress(OSError):
                    os.unlink(final_path.name, dir_fd=user_descriptor)
                with suppress(OSError):
                    os.fsync(user_descriptor)
            raise StorageError("private_storage_unavailable", "私有文件存储不可用") from None
        finally:
            for descriptor in (staging_descriptor, user_descriptor, root_descriptor):
                if descriptor is not None:
                    with suppress(OSError):
                        os.close(descriptor)

    def discard_staged(self, staged: StagedUpload, expected_user_id: uuid.UUID) -> None:
        if not staged.isolated:
            self.remove(staged.storage_key, expected_user_id)
            return
        final_path = self.path_for_key(staged.storage_key, expected_user_id)
        expected_staged_path = final_path.parent / ".staging" / f"{final_path.stem}.fit.part"
        if staged.path != expected_staged_path:
            raise StorageError("invalid_staged_upload", "暂存文件状态无效")
        self._unlink_generated(expected_user_id, staged.path.name, isolated=True)

    def list_user_ids(self) -> list[uuid.UUID]:
        try:
            entries = list(self.root.iterdir())
        except FileNotFoundError:
            return []
        except (OSError, RuntimeError):
            raise StorageError("private_storage_unavailable", "私有文件存储不可用") from None
        user_ids: list[uuid.UUID] = []
        for entry in entries:
            try:
                user_id = uuid.UUID(entry.name)
                if entry.is_dir() and not entry.is_symlink():
                    user_ids.append(user_id)
            except (ValueError, OSError):
                continue
        return sorted(user_ids, key=str)

    def generated_files(self, user_id: uuid.UUID) -> list[GeneratedPrivateFile]:
        files: list[GeneratedPrivateFile] = []
        files.extend(self._generated_in_directory(user_id, isolated=False))
        files.extend(self._generated_in_directory(user_id, isolated=True))
        return files

    def cleanup_user_orphans(
        self,
        user_id: uuid.UUID,
        referenced_storage_keys: set[str],
    ) -> tuple[int, int]:
        removed_count = 0
        removed_bytes = 0
        for candidate in self.generated_files(user_id):
            if not candidate.isolated and candidate.storage_key in referenced_storage_keys:
                continue
            self.remove_generated(candidate)
            removed_count += 1
            removed_bytes += candidate.size_bytes
        return removed_count, removed_bytes

    def remove_generated(self, candidate: GeneratedPrivateFile) -> None:
        self._unlink_generated(candidate.user_id, candidate.filename, candidate.isolated)

    def _generated_in_directory(
        self, user_id: uuid.UUID, *, isolated: bool
    ) -> list[GeneratedPrivateFile]:
        root_descriptor: int | None = None
        user_descriptor: int | None = None
        target_descriptor: int | None = None
        directory_flags = (
            os.O_RDONLY
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_DIRECTORY", 0)
        )
        try:
            root_descriptor = os.open(self.root, directory_flags)
            user_descriptor = os.open(str(user_id), directory_flags, dir_fd=root_descriptor)
            target_descriptor = user_descriptor
            if isolated:
                target_descriptor = os.open(".staging", directory_flags, dir_fd=user_descriptor)
            result: list[GeneratedPrivateFile] = []
            for filename in os.listdir(target_descriptor):
                import_id = self._generated_import_id(filename, isolated=isolated)
                if import_id is None:
                    continue
                file_stat = os.stat(
                    filename,
                    dir_fd=target_descriptor,
                    follow_symlinks=False,
                )
                if not stat.S_ISREG(file_stat.st_mode):
                    continue
                result.append(
                    GeneratedPrivateFile(
                        user_id=user_id,
                        filename=filename,
                        storage_key=None if isolated else f"{user_id}/{import_id}.fit",
                        size_bytes=file_stat.st_size,
                        modified_at=datetime.fromtimestamp(file_stat.st_mtime, tz=UTC),
                        isolated=isolated,
                    )
                )
            return result
        except FileNotFoundError:
            return []
        except (OSError, RuntimeError):
            raise StorageError("private_storage_unavailable", "私有文件存储不可用") from None
        finally:
            descriptors = [target_descriptor]
            if target_descriptor == user_descriptor:
                descriptors = []
            for descriptor in (*descriptors, user_descriptor, root_descriptor):
                if descriptor is not None:
                    with suppress(OSError):
                        os.close(descriptor)

    @staticmethod
    def _generated_import_id(filename: str, *, isolated: bool) -> uuid.UUID | None:
        suffix = ".fit.part" if isolated else ".fit"
        if not filename.endswith(suffix):
            return None
        try:
            return uuid.UUID(filename[: -len(suffix)])
        except ValueError:
            return None

    def _unlink_generated(self, user_id: uuid.UUID, filename: str, isolated: bool) -> None:
        if self._generated_import_id(filename, isolated=isolated) is None:
            raise StorageError("invalid_storage_key", "私有文件路径无效")
        root_descriptor: int | None = None
        user_descriptor: int | None = None
        target_descriptor: int | None = None
        directory_flags = (
            os.O_RDONLY
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_DIRECTORY", 0)
        )
        try:
            root_descriptor = os.open(self.root, directory_flags)
            user_descriptor = os.open(str(user_id), directory_flags, dir_fd=root_descriptor)
            target_descriptor = user_descriptor
            if isolated:
                target_descriptor = os.open(".staging", directory_flags, dir_fd=user_descriptor)
            with suppress(FileNotFoundError):
                os.unlink(filename, dir_fd=target_descriptor)
        except FileNotFoundError:
            return
        except (OSError, RuntimeError):
            raise StorageError("private_storage_unavailable", "私有文件存储不可用") from None
        finally:
            descriptors = [target_descriptor]
            if target_descriptor == user_descriptor:
                descriptors = []
            for descriptor in (*descriptors, user_descriptor, root_descriptor):
                if descriptor is not None:
                    with suppress(OSError):
                        os.close(descriptor)

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
