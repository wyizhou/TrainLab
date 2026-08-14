from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.mail_agent.poll import MailPollConfig, MailPollError, MailPollService


def service(tmp_path: Path) -> MailPollService:
    data = tmp_path / "data"
    raw = data / "raw"
    data.mkdir(mode=0o700)
    raw.mkdir(mode=0o700)
    value = object.__new__(MailPollService)
    value.config = MailPollConfig(raw, tmp_path / "lock")
    return value


def test_raw_winner_then_loser_without_foundation(tmp_path: Path) -> None:
    value = service(tmp_path)
    payload = b'{"safe":true}'
    digest = hashlib.sha256(payload).hexdigest()
    when = datetime(2026, 7, 1, tzinfo=timezone.utc)
    _, winner = value._archive_raw(payload, digest, when)
    _, loser = value._archive_raw(payload, digest, when)
    assert winner is True and loser is False


def test_raw_rejects_year_symlink_without_outside_write(tmp_path: Path) -> None:
    value = service(tmp_path)
    raw = value.config.raw_root
    (raw / "gmail" / "json").mkdir(parents=True, mode=0o700)
    outside = tmp_path / "outside"
    outside.mkdir(mode=0o700)
    (raw / "gmail" / "json" / "2026").symlink_to(outside, target_is_directory=True)
    payload = b"x"
    digest = hashlib.sha256(payload).hexdigest()
    with pytest.raises(MailPollError):
        value._archive_raw(payload, digest, datetime(2026, 7, 1, tzinfo=timezone.utc))
    assert not list(outside.iterdir())


def test_short_write_completes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    value = service(tmp_path)
    payload = b"abcdef"
    digest = hashlib.sha256(payload).hexdigest()
    original = os.write
    monkeypatch.setattr(
        os, "write", lambda fd, data: original(fd, data[:1]) if data else 0
    )
    assert (
        value._archive_raw(payload, digest, datetime(2026, 7, 1, tzinfo=timezone.utc))[
            1
        ]
        is True
    )


def test_zero_write_cleans_temp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    value = service(tmp_path)
    payload = b"x"
    digest = hashlib.sha256(payload).hexdigest()
    monkeypatch.setattr(os, "write", lambda _fd, _data: 0)
    with pytest.raises(MailPollError):
        value._archive_raw(payload, digest, datetime(2026, 7, 1, tzinfo=timezone.utc))
    assert not list(value.config.raw_root.rglob("*.tmp")) and not list(
        value.config.raw_root.rglob("*.json")
    )


def test_write_error_cleans_temp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    value = service(tmp_path)
    payload = b"x"
    digest = hashlib.sha256(payload).hexdigest()
    monkeypatch.setattr(
        os, "write", lambda _fd, _data: (_ for _ in ()).throw(OSError("target"))
    )
    with pytest.raises(MailPollError):
        value._archive_raw(payload, digest, datetime(2026, 7, 1, tzinfo=timezone.utc))
    assert not list(value.config.raw_root.rglob("*.tmp")) and not list(
        value.config.raw_root.rglob("*.json")
    )


def test_corrupt_temp_is_verified_before_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    value = service(tmp_path)
    payload = b'{"safe":true}'
    digest = hashlib.sha256(payload).hexdigest()
    original = os.write
    monkeypatch.setattr(os, "write", lambda fd, data: original(fd, b"x" * len(data)))
    with pytest.raises(MailPollError):
        value._archive_raw(payload, digest, datetime(2026, 7, 1, tzinfo=timezone.utc))
    assert not list(value.config.raw_root.rglob("*.tmp"))
    assert not list(value.config.raw_root.rglob("*.json"))


def test_wrong_raw_mode_rejected(tmp_path: Path) -> None:
    value = service(tmp_path)
    os.chmod(value.config.raw_root, 0o755)
    payload = b"x"
    with pytest.raises(MailPollError):
        value._archive_raw(
            payload,
            hashlib.sha256(payload).hexdigest(),
            datetime(2026, 7, 1, tzinfo=timezone.utc),
        )


def test_component_before_open_replacement_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    value = service(tmp_path)
    (value.config.raw_root / "gmail").mkdir(mode=0o700)
    original = os.open
    switched = False

    def guarded(name, *args, **kwargs):
        nonlocal switched
        if name == "gmail" and kwargs.get("dir_fd") is not None and not switched:
            switched = True
            os.rename(
                value.config.raw_root / "gmail", value.config.raw_root / "gmail-old"
            )
            (value.config.raw_root / "gmail").mkdir(mode=0o700)
        return original(name, *args, **kwargs)

    monkeypatch.setattr(os, "open", guarded)
    parent = os.open(value.config.raw_root, os.O_RDONLY)
    try:
        with pytest.raises(MailPollError):
            value._mkdir_openat(parent, "gmail")
    finally:
        os.close(parent)
    assert (value.config.raw_root / "gmail").is_dir() and (
        value.config.raw_root / "gmail-old"
    ).is_dir()


def test_fd_count_does_not_grow_materially(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    value = service(tmp_path)
    baseline = len(os.listdir("/dev/fd"))
    for n in range(100):
        payload = str(n).encode()
        digest = hashlib.sha256(payload).hexdigest()
        value._archive_raw(payload, digest, datetime(2026, 7, 1, tzinfo=timezone.utc))
        value._archive_raw(payload, digest, datetime(2026, 7, 1, tzinfo=timezone.utc))
    original = os.write
    for _ in range(50):
        monkeypatch.setattr(os, "write", lambda _fd, _data: 0)
        with pytest.raises(MailPollError):
            value._archive_raw(
                b"failure",
                hashlib.sha256(b"failure").hexdigest(),
                datetime(2026, 7, 2, tzinfo=timezone.utc),
            )
        monkeypatch.setattr(os, "write", original)
    assert abs(len(os.listdir("/dev/fd")) - baseline) <= 1


def test_raw_lexical_replacement_never_writes_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    value = service(tmp_path)
    original = value._mkdir_openat
    moved = False

    def guarded(parent: int, name: str) -> int:
        nonlocal moved
        if name == "gmail" and not moved:
            moved = True
            os.rename(value.config.raw_root, value.config.raw_root.with_name("raw-old"))
            value.config.raw_root.mkdir(mode=0o700)
        return original(parent, name)

    monkeypatch.setattr(value, "_mkdir_openat", guarded)
    payload = b"x"
    with pytest.raises(MailPollError):
        value._archive_raw(
            payload,
            hashlib.sha256(payload).hexdigest(),
            datetime(2026, 7, 1, tzinfo=timezone.utc),
        )
    assert not list(value.config.raw_root.rglob("*.json"))


def test_final_replaced_during_read_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    value = service(tmp_path)
    payload = b"x"
    digest = hashlib.sha256(payload).hexdigest()
    when = datetime(2026, 7, 1, tzinfo=timezone.utc)
    relative, _ = value._archive_raw(payload, digest, when)
    final = tmp_path / "data" / relative
    fd = os.open(final.parent, os.O_RDONLY)
    original = os.read
    switched = False

    def guarded(target: int, size: int):
        nonlocal switched
        chunk = original(target, size)
        if not switched:
            switched = True
            replacement = final.with_suffix(".new")
            replacement.write_bytes(payload)
            os.chmod(replacement, 0o600)
            os.replace(replacement, final)
        return chunk

    monkeypatch.setattr(os, "read", guarded)
    try:
        with pytest.raises(MailPollError):
            value._verify_raw_fd(fd, final.name, payload, digest)
    finally:
        os.close(fd)
