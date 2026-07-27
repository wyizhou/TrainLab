from __future__ import annotations

import hashlib
import hmac
import os
import sqlite3
import stat
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from trainlab.foundation import FoundationConfig, FoundationRequest, FoundationTool
from trainlab.mail_agent.environment_adapter import (
    GmailEnvironmentAdapterError,
    GmailEnvironmentRecipientAdapter,
)


NOW = "2026-07-27T00:00:00Z"
RECIPIENT = "Authorized@Example.com"


def foundation(tmp_path: Path) -> FoundationConfig:
    root = tmp_path / "foundation"
    config = FoundationConfig(root, root / "data.db", root / "raw", root / "state", root / "state" / "foundation-ready.json", root / "state" / "locks" / "foundation.lock")
    assert FoundationTool(config).execute(FoundationRequest("init", "mail-identity", NOW)).status == "initialized"
    with sqlite3.connect(config.database_path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("INSERT INTO data_subjects(id,subject_key,created_at_utc) VALUES(1,'subject-1',?)", (NOW,))
    return config


def adapter(config: FoundationConfig) -> GmailEnvironmentRecipientAdapter:
    return GmailEnvironmentRecipientAdapter(RECIPIENT, identity_state_root=config.state_root)


def prepare(config: FoundationConfig) -> int:
    with sqlite3.connect(config.database_path, timeout=5) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        value = adapter(config)
        assert value.prepare(connection, 1).email == RECIPIENT.lower()
        assert value.verified_identity_id is not None
        return value.verified_identity_id


def test_configured_recipient_is_hmac_anchored_idempotently_without_plaintext(tmp_path: Path) -> None:
    config = foundation(tmp_path)
    first = prepare(config)
    second = prepare(config)
    key_path = config.state_root / "secrets" / "gmail-recipient-identity.key"
    assert first == second
    assert stat.S_IMODE((config.state_root / "secrets").stat().st_mode) == 0o700
    assert stat.S_IMODE(key_path.stat().st_mode) == 0o600
    with sqlite3.connect(config.database_path) as connection:
        row = connection.execute("SELECT subject_id,identity_hmac,is_verified FROM subject_identities").fetchone()
        assert row[0] == 1 and row[2] == 1
        assert row[1] == hmac.new(key_path.read_bytes(), RECIPIENT.lower().encode("ascii"), hashlib.sha256).hexdigest()
        assert RECIPIENT.lower() not in str(row)


def test_identity_existing_for_another_subject_fails_closed(tmp_path: Path) -> None:
    config = foundation(tmp_path)
    key_dir = config.state_root / "secrets"; key_dir.mkdir(mode=0o700)
    key = b"x" * 32
    key_path = key_dir / "gmail-recipient-identity.key"; key_path.write_bytes(key); os.chmod(key_path, 0o600)
    digest = hmac.new(key, RECIPIENT.lower().encode("ascii"), hashlib.sha256).hexdigest()
    with sqlite3.connect(config.database_path) as connection:
        connection.execute("INSERT INTO data_subjects(id,subject_key,created_at_utc) VALUES(2,'subject-2',?)", (NOW,))
        connection.execute("INSERT INTO subject_identities(subject_id,provider,identity_kind,identity_hmac,is_verified,first_seen_at_utc,last_seen_at_utc) VALUES(2,'gmail','email',?,1,?,?)", (digest, NOW, NOW))
    with pytest.raises(GmailEnvironmentAdapterError, match="^gmail_reply_identity_conflict$"):
        prepare(config)


def test_only_subject_one_may_bind_the_fixed_mail_recipient(tmp_path: Path) -> None:
    config = foundation(tmp_path)
    with sqlite3.connect(config.database_path) as connection:
        with pytest.raises(GmailEnvironmentAdapterError, match="^gmail_reply_subject_invalid$"):
            adapter(config).prepare(connection, 2)


def test_simultaneous_provisioning_converges_to_one_verified_identity(tmp_path: Path) -> None:
    config = foundation(tmp_path)
    with ThreadPoolExecutor(max_workers=2) as pool:
        identities = list(pool.map(lambda _: prepare(config), range(2)))
    assert identities[0] == identities[1]
    with sqlite3.connect(config.database_path) as connection:
        assert connection.execute("SELECT count(*) FROM subject_identities WHERE provider='gmail' AND identity_kind='email'").fetchone()[0] == 1


def test_simultaneous_first_start_accepts_directory_create_winner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = foundation(tmp_path)
    secrets_dir = config.state_root / "secrets"
    assert not secrets_dir.exists()
    barrier = threading.Barrier(2)
    lock = threading.Lock()
    first_calls: set[int] = set()
    real_lstat = os.lstat

    def raced_lstat(path: object):
        if Path(path) == secrets_dir:
            identity = threading.get_ident()
            with lock:
                first = identity not in first_calls
                first_calls.add(identity)
            if first:
                barrier.wait(timeout=5)
                raise FileNotFoundError(str(path))
        return real_lstat(path)

    monkeypatch.setattr(
        "trainlab.mail_agent.environment_adapter.os.lstat", raced_lstat
    )
    with ThreadPoolExecutor(max_workers=2) as pool:
        identities = list(pool.map(lambda _: prepare(config), range(2)))
    assert identities[0] == identities[1]
