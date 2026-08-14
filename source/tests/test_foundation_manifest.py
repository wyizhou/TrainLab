from __future__ import annotations

import copy
import json
import sqlite3
from pathlib import Path

from src.foundation import (
    FoundationConfig,
    FoundationRequest,
    FoundationTool,
    validate_schema_manifest,
)
from src.resources import resource_bytes


def tool(root: Path) -> FoundationTool:
    return FoundationTool(
        FoundationConfig(
            root,
            root / "data.db",
            root / "raw",
            root / "state",
            root / "state/foundation-ready.json",
            root / "state/locks/foundation.lock",
        )
    )


def request(mode: str) -> FoundationRequest:
    return FoundationRequest(
        mode=mode,
        invocation_id="manifest-test",
        requested_at_utc="2026-07-23T00:00:00Z",
    )


def manifest() -> dict:
    return json.loads(resource_bytes("harness/schemas/foundation_schema_manifest.json"))


def test_manifest_accepts_clean_database(tmp_path: Path) -> None:
    instance = tool(tmp_path / "f")
    assert instance.execute(request("init")).status == "initialized"
    conn = sqlite3.connect(tmp_path / "f" / "data.db")
    assert validate_schema_manifest(conn, manifest()) == []


def test_manifest_negative_index_view_and_verify_receipts(tmp_path: Path) -> None:
    root = tmp_path / "f"
    instance = tool(root)
    assert instance.execute(request("init")).status == "initialized"
    conn = sqlite3.connect(root / "data.db")
    conn.execute("DROP INDEX ux_source_revision_current")
    assert (
        "current_unique:source_revisions:provider,resource_kind,provider_object_id"
        in validate_schema_manifest(conn, manifest())
    )
    conn.close()
    receipt = instance.execute(request("verify"))
    assert receipt.status == "incompatible" and receipt.next_action == "operator_review"

    root2 = tmp_path / "g"
    instance2 = tool(root2)
    assert instance2.execute(request("init")).status == "initialized"
    conn = sqlite3.connect(root2 / "data.db")
    conn.execute("DROP VIEW v_current_daily_health")
    conn.execute("CREATE VIEW v_current_daily_health AS SELECT * FROM daily_health")
    assert "view:v_current_daily_health" in validate_schema_manifest(conn, manifest())
    conn.close()
    receipt = instance2.execute(request("verify"))
    assert receipt.status == "incompatible" and receipt.next_action == "operator_review"


def test_manifest_detects_missing_sets_unique_and_enum(tmp_path: Path) -> None:
    root = tmp_path / "f"
    instance = tool(root)
    assert instance.execute(request("init")).status == "initialized"
    conn = sqlite3.connect(root / "data.db")
    broken = copy.deepcopy(manifest())
    broken["tables"]["not_a_table"] = {"owner": "x", "columns": []}
    assert "table_set_mismatch" in validate_schema_manifest(conn, broken)
    broken = copy.deepcopy(manifest())
    broken["views"]["not_a_view"] = {"source": "x"}
    assert "view_set_mismatch" in validate_schema_manifest(conn, broken)
    broken = copy.deepcopy(manifest())
    broken["tables"]["activities"]["unique"].append(["provider", "name"])
    assert "unique:activities:provider,name" in validate_schema_manifest(conn, broken)
    broken = copy.deepcopy(manifest())
    broken["tables"]["activities"]["enums"]["provider_state"].append("wrong")
    assert "enum:activities:provider_state" in validate_schema_manifest(conn, broken)
