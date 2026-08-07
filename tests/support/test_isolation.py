from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from tests.support.isolation import (
    IsolatedTestSubject,
    IsolationError,
    MarkedTestMail,
    create_isolated_test_subject,
    reject_production_path,
    require_marked_self_mail,
)

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = ROOT / "harness" / "schemas" / "test_acceptance_receipt.schema.json"
FIXTURE = ROOT / "tests" / "fixtures" / "test_isolation_synthetic.json"
PARTITIONS = (
    "synthetic-fixture",
    "production-db-path",
    "private-raw-path",
    "credential-path",
    "marked-test-mail",
    "unmarked-mail",
)


def test_synthetic_fixture_is_data_free_and_uses_reserved_recipient() -> None:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert fixture["fixture_kind"] == "synthetic_test_isolation"
    assert fixture["mail_recipient"].endswith("@example.invalid")
    forbidden = {"email", "heart_rate", "weight", "sleep", "fit", "token"}
    assert not forbidden.intersection(fixture)


def test_test_subject_roots_are_unique_disposable_and_schema_valid() -> None:
    first = create_isolated_test_subject(test_name="isolation")
    second = create_isolated_test_subject(test_name="isolation")
    try:
        assert first.root != second.root
        assert first.database_path.parent == first.root
        assert first.raw_root.parent == first.root
        assert first.state_root.parent == first.root
        assert first.root.is_dir() and second.root.is_dir()
        jsonschema.Draft202012Validator(json.loads(SCHEMA.read_text())).validate(
            first.acceptance_receipt(partitions=PARTITIONS)
        )
    finally:
        for subject in (first, second):
            for path in sorted(subject.root.rglob("*"), reverse=True):
                if path.is_file():
                    path.unlink()
                elif path.is_dir():
                    path.rmdir()
            subject.root.rmdir()


@pytest.mark.parametrize(
    ("path", "error"),
    (
        (ROOT / "data.db", "test_isolation_production_db_path_rejected"),
        (
            ROOT / "state" / "raw" / "private.json",
            "test_isolation_private_raw_path_rejected",
        ),
        (ROOT / "credentials.json", "test_isolation_credential_path_rejected"),
    ),
)
def test_production_private_and_credential_paths_are_rejected(
    path: Path,
    error: str,
) -> None:
    with pytest.raises(IsolationError, match=f"^{error}$"):
        reject_production_path(path)


def test_marked_test_mail_requires_unique_marker_and_configured_self_recipient(
    isolated_test_subject: IsolatedTestSubject,
) -> None:
    mail = isolated_test_subject.marked_mail(subject="TrainLab acceptance")
    require_marked_self_mail(mail, subject=isolated_test_subject)


@pytest.mark.parametrize(
    "mail",
    (
        MarkedTestMail(
            "other@example.invalid", "TrainLab-Test:any", "TrainLab-Test:any"
        ),
        MarkedTestMail("self@example.invalid", "", "unmarked"),
    ),
)
def test_unmarked_or_nonself_mail_is_rejected(
    isolated_test_subject: IsolatedTestSubject,
    mail: MarkedTestMail,
) -> None:
    with pytest.raises(IsolationError):
        require_marked_self_mail(mail, subject=isolated_test_subject)
