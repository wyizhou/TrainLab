"""Offline-only evidence comparison for the A3-24 shadow migration gate.

This module intentionally accepts only redacted identifiers, counts, and
SHA-256 values.  It neither executes a runner nor accesses a database,
filesystem, network, mailbox, or production configuration.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Literal


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


class ShadowEvidenceError(ValueError):
    """Raised when an evidence manifest is not safely redacted or coherent."""


@dataclass(frozen=True)
class RedactedShadowEvidence:
    """A non-sensitive, already-produced route evidence manifest.

    ``role='shadow'`` is the only candidate route.  Its non-current and
    no-email invariants are mandatory; the legacy manifest may describe an
    already-published production result for comparison purposes.
    """

    role: Literal["legacy", "shadow"]
    subject_id: str
    logical_local_date: str
    input_manifest_sha256: str
    output_sha256: str
    artifact_ids: tuple[str, ...]
    artifact_count: int
    delivery_count: int
    current_published: bool
    email_sent: bool

    def validate(self) -> None:
        if not _ID.fullmatch(self.subject_id):
            raise ShadowEvidenceError("shadow_subject_id_invalid")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", self.logical_local_date):
            raise ShadowEvidenceError("shadow_logical_date_invalid")
        if not _SHA256.fullmatch(self.input_manifest_sha256):
            raise ShadowEvidenceError("shadow_input_hash_invalid")
        if not _SHA256.fullmatch(self.output_sha256):
            raise ShadowEvidenceError("shadow_output_hash_invalid")
        if self.artifact_count != len(self.artifact_ids) or self.artifact_count < 0:
            raise ShadowEvidenceError("shadow_artifact_count_invalid")
        if len(set(self.artifact_ids)) != len(self.artifact_ids):
            raise ShadowEvidenceError("shadow_artifact_ids_not_unique")
        if any(_ID.fullmatch(value) is None for value in self.artifact_ids):
            raise ShadowEvidenceError("shadow_artifact_id_invalid")
        if self.delivery_count < 0:
            raise ShadowEvidenceError("shadow_delivery_count_invalid")
        if self.role == "shadow" and (self.current_published or self.email_sent):
            raise ShadowEvidenceError("shadow_side_effect_invariant_failed")


@dataclass(frozen=True)
class ShadowComparison:
    """Pure go/no-go result; a ``go`` never executes a cutover."""

    decision: Literal["go", "no_go"]
    codes: tuple[str, ...]
    subject_id: str
    logical_local_date: str
    input_hash_matches: bool
    output_hash_matches: bool
    artifact_count_matches: bool
    release_authorization_declared: bool


def compare_shadow_evidence(
    legacy: RedactedShadowEvidence,
    shadow: RedactedShadowEvidence,
    *,
    release_authorization_declared: bool = False,
) -> ShadowComparison:
    """Compare pre-collected redacted evidence without running either path.

    A separate release authorization is required even for a ``go`` comparison;
    this function merely assesses whether the supplied evidence is eligible for
    human review.  It cannot publish a current revision or send email.
    """

    if type(release_authorization_declared) is not bool:
        raise ShadowEvidenceError("shadow_release_authorization_invalid")
    legacy.validate()
    shadow.validate()
    if legacy.role != "legacy" or shadow.role != "shadow":
        raise ShadowEvidenceError("shadow_roles_invalid")

    codes: list[str] = []
    same_target = (
        legacy.subject_id == shadow.subject_id
        and legacy.logical_local_date == shadow.logical_local_date
    )
    if not same_target:
        codes.append("target_mismatch")
    if shadow.current_published:
        codes.append("shadow_current_publication_forbidden")
    if shadow.email_sent or shadow.delivery_count != 0:
        codes.append("shadow_email_forbidden")
    input_hash_matches = legacy.input_manifest_sha256 == shadow.input_manifest_sha256
    output_hash_matches = legacy.output_sha256 == shadow.output_sha256
    artifact_count_matches = legacy.artifact_count == shadow.artifact_count
    if not input_hash_matches:
        codes.append("input_manifest_mismatch")
    if not output_hash_matches:
        codes.append("output_hash_mismatch")
    if not artifact_count_matches:
        codes.append("artifact_count_mismatch")
    if not release_authorization_declared:
        codes.append("release_authorization_required")

    return ShadowComparison(
        decision="go" if not codes else "no_go",
        codes=tuple(codes),
        subject_id=shadow.subject_id,
        logical_local_date=shadow.logical_local_date,
        input_hash_matches=input_hash_matches,
        output_hash_matches=output_hash_matches,
        artifact_count_matches=artifact_count_matches,
        release_authorization_declared=release_authorization_declared,
    )
