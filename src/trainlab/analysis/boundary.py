"""A3-01 contract snapshot and static dependency boundary for Layer 3.

The functions in this module are deliberately read-only.  They make the
frozen five-layer contract and the current production/Harness migration
baseline explicit before any analysis implementation is allowed to exist.
"""

from __future__ import annotations

import ast
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


MODULE_VERSION = "0.1.0-a3-01"
MANIFEST_SCHEMA_VERSION = "1"
LAYER_NAME = "analysis"
CURRENT_PRODUCTION_ENTRYPOINT = "trainlab run"

FROZEN_CONTRACT_SHA256: dict[str, str] = {
    "docs/layers/01-data-foundation.md": "9bf0a91e61bda47c9dba971c731ca6ec79e064b7f0ea4eb8124a5a216d67e396",
    "docs/layers/02-data-collection.md": "c39ae1b82afcafe9f4fc3c54d1f851b4992c48021c5238038f078fab1ec885d6",
    "docs/layers/03-data-analysis.md": "98652387c7018138e7910dbdf83826cb1e6b7a2a830d1bd4d67debe4627f0956",
    "docs/layers/04-mail-agent.md": "977246c604dc939cce1d97869f584e463030476db64b0d20e07bb625faa12e17",
    "docs/layers/05-orchestration-monitoring.md": "f46aca332f146fa2efffb4da8a03b48037989b7e4e4f31df9d562932e46db356",
}

# This is a historical A3-01 snapshot, deliberately not a view of the files
# currently on disk.  Later controlled Harness migrations must never rewrite
# the starting evidence that the migration is meant to audit against.
INITIAL_MIGRATION_BASELINE: dict[str, str] = {
    "AGENTS.md": "74aebb78f0e0eed24a8d4fa2b38cfed784cb1c2d04e39e774b44025e7bc3ad85",
    "harness/shared/HARNESS.md": "847ec27f06e4d3955aa6064777c15870054ed9fcc61e3d406ec89f8c5fca15c9",
    "harness/runtime/HARNESS.md": "824b4704635656eb6ebc410d90de9baf956b2fcd8d959f2fefdd61dac5b4ee66",
}

# A3-01 describes component ownership but does not implement the components.
COMPONENT_RESPONSIBILITIES: dict[str, str] = {
    "request": "Future versioned request and receipt boundary; no CLI implementation in A3-01.",
    "repository": "Future stable-view reads and Layer 3 writes only; no database access in A3-01.",
    "features": "Future deterministic analysis features; no provider re-computation in A3-01.",
    "context": "Future bounded context and provenance assembly; no raw provider input in A3-01.",
    "quality_gate": "Future route quality decision; no cursor or gap mutation in A3-01.",
    "harness": "Future allowlisted Harness resolver; no Harness loading in A3-01.",
    "runner": "Future isolated Codex runner; no subprocess or model invocation in A3-01.",
    "validators": "Future output and safety validation; no generation in A3-01.",
    "publisher": "Future atomic Layer 3 publication; no database write in A3-01.",
    "delivery": "Future self-only artifact delivery; no Gmail/MCP use in A3-01.",
}

# These are legacy or other-layer adapters.  A third-layer module must not
# import them directly; future shared abstractions require an explicit plan item.
FORBIDDEN_FIRST_PARTY_MODULES: frozenset[str] = frozenset(
    {
        "trainlab.cli",
        "trainlab.context",
        "trainlab.deploy",
        "trainlab.garmin",
        "trainlab.garmin_catalog",
        "trainlab.garmin_client",
        "trainlab.garmin_config",
        "trainlab.garmin_quality",
        "trainlab.gmail_mcp_server",
        "trainlab.ingest",
        "trainlab.mail",
        "trainlab.mcp",
        "trainlab.runner",
        "trainlab.scheduler",
        "trainlab.sync",
        "trainlab.watchdog",
    }
)


class AnalysisBoundaryError(RuntimeError):
    """Raised when the frozen Layer 3 boundary cannot be proven."""


@dataclass(frozen=True)
class FileSnapshot:
    """Content-addressed, read-only evidence for a file used as a baseline."""

    relative_path: str
    sha256: str


@dataclass(frozen=True)
class AnalysisModuleManifest:
    """Serializable A3-01 manifest with no operational capabilities."""

    schema_version: str
    layer: str
    module_version: str
    production_entrypoint: str
    contracts: tuple[FileSnapshot, ...]
    migration_baseline: tuple[FileSnapshot, ...]
    components: dict[str, str]
    forbidden_first_party_modules: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "layer": self.layer,
            "module_version": self.module_version,
            "production_entrypoint": self.production_entrypoint,
            "contracts": [snapshot.__dict__ for snapshot in self.contracts],
            "migration_baseline": [snapshot.__dict__ for snapshot in self.migration_baseline],
            "components": self.components,
            "forbidden_first_party_modules": list(self.forbidden_first_party_modules),
        }

    def to_json(self) -> str:
        return json.dumps(self.as_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _snapshot(project_root: Path, relative_path: str) -> FileSnapshot:
    path = project_root / relative_path
    if not path.is_file():
        raise AnalysisBoundaryError(f"analysis_baseline_file_missing:{relative_path}")
    return FileSnapshot(relative_path=relative_path, sha256=_sha256_file(path))


def verify_contract_snapshot(project_root: Path) -> tuple[FileSnapshot, ...]:
    """Return the frozen contract evidence or block on a SHA-256 mismatch."""

    snapshots: list[FileSnapshot] = []
    for relative_path, expected_hash in FROZEN_CONTRACT_SHA256.items():
        snapshot = _snapshot(project_root, relative_path)
        if snapshot.sha256 != expected_hash:
            raise AnalysisBoundaryError(
                f"analysis_contract_hash_mismatch:{relative_path}:expected={expected_hash}:actual={snapshot.sha256}"
            )
        snapshots.append(snapshot)
    return tuple(snapshots)


def build_module_manifest(project_root: Path) -> AnalysisModuleManifest:
    """Build a manifest after proving the authoritative contract snapshot."""

    contracts = verify_contract_snapshot(project_root)
    # Do not read current Harness files here.  Their active hashes belong to
    # the A3-04 immutable Harness manifest, while this field preserves the
    # initial migration snapshot from A3-01.
    baseline = tuple(
        FileSnapshot(relative_path=relative_path, sha256=sha256)
        for relative_path, sha256 in INITIAL_MIGRATION_BASELINE.items()
    )
    return AnalysisModuleManifest(
        schema_version=MANIFEST_SCHEMA_VERSION,
        layer=LAYER_NAME,
        module_version=MODULE_VERSION,
        production_entrypoint=CURRENT_PRODUCTION_ENTRYPOINT,
        contracts=contracts,
        migration_baseline=baseline,
        components=dict(COMPONENT_RESPONSIBILITIES),
        forbidden_first_party_modules=tuple(sorted(FORBIDDEN_FIRST_PARTY_MODULES)),
    )


def _forbidden_imports(source_path: Path) -> set[str]:
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    violations: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules = (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            imported_modules = [module, *(f"{module}.{alias.name}" for alias in node.names)]
        else:
            continue
        for imported_module in imported_modules:
            for forbidden in FORBIDDEN_FIRST_PARTY_MODULES:
                if imported_module == forbidden or imported_module.startswith(f"{forbidden}."):
                    violations.add(forbidden)
    return violations


def verify_import_boundary(package_root: Path) -> dict[str, tuple[str, ...]]:
    """Statically prove that the Layer 3 package has no legacy adapter imports."""

    if not package_root.is_dir():
        raise AnalysisBoundaryError(f"analysis_package_missing:{package_root}")
    graph: dict[str, tuple[str, ...]] = {}
    violations: list[str] = []
    for source_path in sorted(package_root.rglob("*.py")):
        imported = tuple(sorted(_forbidden_imports(source_path)))
        graph[source_path.relative_to(package_root).as_posix()] = imported
        violations.extend(f"{source_path}:{module}" for module in imported)
    if violations:
        raise AnalysisBoundaryError("analysis_forbidden_import:" + ",".join(violations))
    return graph
