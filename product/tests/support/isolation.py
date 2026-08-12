"""Test-only isolation primitives.

These helpers create disposable paths below ``state/test-tmp`` and reject
paths that could name local production data or credentials.  They never open a
provider connection or send mail.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4


class IsolationError(ValueError):
    """Raised when a test attempts to use a non-disposable test boundary."""


@dataclass(frozen=True)
class MarkedTestMail:
    """A no-send description for a mail acceptance test."""

    recipient: str
    marker: str
    subject: str


@dataclass(frozen=True)
class IsolatedTestSubject:
    """All filesystem and mail values that belong to one disposable test."""

    subject_id: str
    root: Path
    database_path: Path
    raw_root: Path
    state_root: Path
    self_recipient: str
    mail_marker: str

    def acceptance_receipt(self, *, partitions: tuple[str, ...]) -> dict[str, object]:
        """Return a data-free receipt suitable for schema validation."""

        return {
            "schema_version": "1",
            "receipt_kind": "test_acceptance",
            "run_id": self.subject_id,
            "subject_id": self.subject_id,
            "test_root": str(self.root),
            "database_path": str(self.database_path),
            "raw_root": str(self.raw_root),
            "state_root": str(self.state_root),
            "self_recipient": self.self_recipient,
            "mail_marker": self.mail_marker,
            "partitions": list(partitions),
            "external_effects": False,
        }

    def marked_mail(self, *, subject: str) -> MarkedTestMail:
        """Build the only mail shape permitted for a live acceptance seam."""

        if self.mail_marker not in subject:
            subject = f"{subject} [{self.mail_marker}]"
        return MarkedTestMail(self.self_recipient, self.mail_marker, subject)


_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_TEST_TMP_ROOT = _PROJECT_ROOT / "state" / "test-tmp"
_CREDENTIAL_BASENAMES = frozenset(
    {
        "credentials.json",
        "gcp-oauth.keys.json",
        "gmail-mcp.credentials.json",
        ".env",
        ".env.local",
    }
)
_PRIVATE_ROOTS = (
    _PROJECT_ROOT / "raw",
    _PROJECT_ROOT / "state" / "raw",
    _PROJECT_ROOT / "state" / "foundation" / "raw",
)
_PRODUCTION_DATABASES = (
    _PROJECT_ROOT / "data.db",
    _PROJECT_ROOT / "state" / "data.db",
    _PROJECT_ROOT / "state" / "foundation" / "data.db",
)


def _resolved(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def _is_within(candidate: Path, parent: Path) -> bool:
    try:
        candidate.relative_to(parent)
    except ValueError:
        return False
    return True


def reject_production_path(path: Path | str) -> Path:
    """Return a safe disposable path or reject production/private locations."""

    candidate = _resolved(Path(path))
    if candidate.name in _CREDENTIAL_BASENAMES:
        raise IsolationError("test_isolation_credential_path_rejected")
    if any(_is_within(candidate, _resolved(root)) for root in _PRIVATE_ROOTS):
        raise IsolationError("test_isolation_private_raw_path_rejected")
    if candidate in {_resolved(item) for item in _PRODUCTION_DATABASES}:
        raise IsolationError("test_isolation_production_db_path_rejected")
    if not _is_within(candidate, _TEST_TMP_ROOT):
        raise IsolationError("test_isolation_non_disposable_path_rejected")
    return candidate


def create_isolated_test_subject(*, test_name: str) -> IsolatedTestSubject:
    """Create one unique, owner-only disposable test subject.

    The generated recipient uses the reserved ``example.invalid`` domain and
    is only an assertion value.  This function has no network or mailbox
    effects.
    """

    normalized = "".join(character for character in test_name if character.isalnum())
    if not normalized:
        raise IsolationError("test_isolation_name_invalid")
    token = uuid4().hex
    subject_id = f"test-{normalized.lower()}-{token}"
    root = reject_production_path(_TEST_TMP_ROOT / subject_id)
    root.mkdir(parents=True, mode=0o700, exist_ok=False)
    root.chmod(0o700)
    raw_root = root / "raw"
    state_root = root / "state"
    raw_root.mkdir(mode=0o700)
    state_root.mkdir(mode=0o700)
    return IsolatedTestSubject(
        subject_id=subject_id,
        root=root,
        database_path=root / "data.db",
        raw_root=raw_root,
        state_root=state_root,
        self_recipient=f"{subject_id}@example.invalid",
        mail_marker=f"TrainLab-Test:{token}",
    )


def require_marked_self_mail(
    mail: MarkedTestMail,
    *,
    subject: IsolatedTestSubject,
) -> None:
    """Fail closed unless a mail test targets only its configured self value."""

    recipient = mail.recipient.strip().lower()
    if recipient != subject.self_recipient:
        raise IsolationError("test_isolation_self_recipient_required")
    if not recipient.endswith("@example.invalid"):
        raise IsolationError("test_isolation_non_test_recipient_rejected")
    if mail.marker != subject.mail_marker or mail.marker not in mail.subject:
        raise IsolationError("test_isolation_unique_marker_required")
