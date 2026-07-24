"""A3-04 immutable allowlist resolver for production analysis Harness files."""

from __future__ import annotations

import hashlib
import json
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from jsonschema import Draft202012Validator

from .config import AnalysisConfig


HarnessRoute = Literal["daily", "weekly", "revise_plan", "delivery"]


class HarnessResolutionError(ValueError):
    """Raised before a future Codex runner could receive Harness references."""


@dataclass(frozen=True)
class SchemaEvidence:
    input_schema_version: str
    input_schema_sha256: str
    output_schema_version: str
    output_schema_sha256: str


@dataclass(frozen=True)
class HarnessFileEvidence:
    path_id: str
    sha256: str


@dataclass(frozen=True)
class HarnessBundle:
    route: HarnessRoute
    harness_version: str
    files: tuple[HarnessFileEvidence, ...]
    schema_evidence: SchemaEvidence

    def audit_record(self) -> dict[str, Any]:
        """Return identifiers and hashes only; never persist Harness text."""

        return {
            "route": self.route,
            "harness_version": self.harness_version,
            "files": [{"path_id": item.path_id, "sha256": item.sha256} for item in self.files],
            "input_schema_version": self.schema_evidence.input_schema_version,
            "input_schema_sha256": self.schema_evidence.input_schema_sha256,
            "output_schema_version": self.schema_evidence.output_schema_version,
            "output_schema_sha256": self.schema_evidence.output_schema_sha256,
        }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _manifest() -> dict[str, Any]:
    return json.loads(Path(__file__).with_name("harness_manifest.json").read_text(encoding="utf-8"))


def _manifest_schema() -> dict[str, Any]:
    return json.loads((Path(__file__).with_name("schemas") / "harness_bundle_manifest.schema.json").read_text(encoding="utf-8"))


def _validate_manifest() -> dict[str, Any]:
    payload = _manifest()
    errors = list(Draft202012Validator(_manifest_schema()).iter_errors(payload))
    if errors:
        raise HarnessResolutionError("analysis_harness_manifest_invalid")
    return payload


def _regular_private_readonly_file(path: Path, path_id: str) -> None:
    if path.is_symlink():
        raise HarnessResolutionError(f"analysis_harness_symlink_rejected:{path_id}")
    if not path.is_file():
        raise HarnessResolutionError(f"analysis_harness_file_missing_or_not_regular:{path_id}")
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & 0o022:
        raise HarnessResolutionError(f"analysis_harness_file_writable_by_group_or_other:{path_id}")


def _under_root(root: Path, relative_path: str) -> Path:
    candidate = root / relative_path
    resolved = candidate.resolve()
    if resolved != root and root not in resolved.parents:
        raise HarnessResolutionError(f"analysis_harness_path_escape:{relative_path}")
    return candidate


def _verify_schema(path: Path, expected_sha256: str, label: str) -> None:
    _regular_private_readonly_file(path, label)
    if _sha256(path) != expected_sha256:
        raise HarnessResolutionError(f"analysis_harness_schema_hash_mismatch:{label}")


def resolve_harness_bundle(config: AnalysisConfig, route: HarnessRoute, schema_evidence: SchemaEvidence) -> HarnessBundle:
    """Resolve one fixed bundle without reading/returning prompt bodies."""

    if route not in {"daily", "weekly", "revise_plan", "delivery"}:
        raise HarnessResolutionError("analysis_harness_route_not_allowed")
    root = config.project_root.resolve()
    if config.harness_root.resolve() != root / "harness":
        raise HarnessResolutionError("analysis_harness_root_not_allowed")
    _verify_schema(config.input_schema, schema_evidence.input_schema_sha256, "input_schema")
    _verify_schema(config.output_schema, schema_evidence.output_schema_sha256, "output_schema")
    manifest = _validate_manifest()
    evidence: list[HarnessFileEvidence] = []
    for expected in manifest["bundles"][route]:
        path_id = expected["path"]
        path = _under_root(root, path_id)
        _regular_private_readonly_file(path, path_id)
        actual_hash = _sha256(path)
        if actual_hash != expected["sha256"]:
            raise HarnessResolutionError(f"analysis_harness_content_drift:{path_id}")
        evidence.append(HarnessFileEvidence(path_id=path_id, sha256=actual_hash))
    version_payload = {
        "route": route,
        "files": [item.__dict__ for item in evidence],
        "input_schema_version": schema_evidence.input_schema_version,
        "input_schema_sha256": schema_evidence.input_schema_sha256,
        "output_schema_version": schema_evidence.output_schema_version,
        "output_schema_sha256": schema_evidence.output_schema_sha256,
    }
    harness_version = hashlib.sha256(json.dumps(version_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return HarnessBundle(route=route, harness_version=harness_version, files=tuple(evidence), schema_evidence=schema_evidence)
