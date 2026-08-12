"""Read-only schema-manifest validation for Foundation databases."""
from __future__ import annotations

import re
import sqlite3
from typing import Any


def validate_schema_manifest(conn: sqlite3.Connection, manifest: dict[str, Any]) -> list[str]:
    """Validate the static contract manifest against SQLite metadata."""
    errors: list[str] = []
    actual_tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    actual_views = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='view'")}
    actual_triggers = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
    if set(manifest["tables"]) != actual_tables:
        errors.append("table_set_mismatch")
    if set(manifest["views"]) != actual_views:
        errors.append("view_set_mismatch")
    if set(manifest.get("triggers", {})) != actual_triggers:
        errors.append("trigger_set_mismatch")
    for name, spec in manifest["tables"].items():
        if name not in actual_tables:
            continue
        table_info = list(conn.execute(f"PRAGMA table_info({name})"))
        columns = {row[1] for row in table_info}
        primary_key = [row[1] for row in sorted((row for row in table_info if row[5]), key=lambda row: row[5])]
        if not set(spec["columns"]) <= columns:
            errors.append(f"columns:{name}")
        foreign = {row[3]: row[2] for row in conn.execute(f"PRAGMA foreign_key_list({name})")}
        if any(foreign.get(column) != target for column, target in spec.get("fk", {}).items()):
            errors.append(f"fk:{name}")
        sql = re.sub(r"\s+", "", conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone()[0]).lower()
        indexes = []
        for item in conn.execute(f"PRAGMA index_list({name})"):
            index_name, unique, partial = item[1], item[2], item[4]
            index_sql_row = conn.execute("SELECT sql FROM sqlite_master WHERE type='index' AND name=?", (index_name,)).fetchone()
            indexes.append(([row[2] for row in conn.execute(f"PRAGMA index_info({index_name})")], bool(unique), bool(partial), "" if not index_sql_row else index_sql_row[0] or ""))
        for fields in spec.get("unique", []):
            if fields != primary_key and not any(unique and cols == fields for cols, unique, _partial, _statement in indexes):
                errors.append(f"unique:{name}:{','.join(fields)}")
        for kind, marker in (("current_unique", "whereis_current=1"), ("active_unique", "whereis_active=1")):
            for fields in spec.get(kind, []):
                if not any(unique and partial and cols == fields and marker in re.sub(r"\s+", "", statement).lower() for cols, unique, partial, statement in indexes):
                    errors.append(f"{kind.split('_')[0]}_unique:{name}:{','.join(fields)}")
        for partial_spec in spec.get("partial_unique", []):
            fields = partial_spec["columns"]
            where = re.sub(r"\s+", "", partial_spec["where"]).lower()
            if not any(unique and partial and cols == fields and f"where{where}" in re.sub(r"\s+", "", statement).lower() for cols, unique, partial, statement in indexes):
                errors.append(f"partial_unique:{name}:{','.join(fields)}")
        for column, choices in spec.get("enums", {}).items():
            match = re.search(re.escape(column.lower()) + r"text.*?check\(([^)]*)\)", sql)
            if match is None or not all(f"'{choice}'" in match.group(1) for choice in choices):
                errors.append(f"enum:{name}:{column}")
    for name, spec in manifest["views"].items():
        if name not in actual_views:
            continue
        sql = re.sub(r"\s+", "", conn.execute("SELECT sql FROM sqlite_master WHERE type='view' AND name=?", (name,)).fetchone()[0]).lower()
        normal = lambda value: re.sub(r"\s+", "", value).lower()
        if normal(spec["source"]) not in sql or ("filter" in spec and normal(spec["filter"]) not in sql) or ("order" in spec and normal(spec["order"]) not in sql) or ("trust_marker" in spec and normal(spec["trust_marker"]) not in sql):
            errors.append(f"view:{name}")
    for name, spec in manifest.get("triggers", {}).items():
        row = conn.execute("SELECT tbl_name,sql FROM sqlite_master WHERE type='trigger' AND name=?", (name,)).fetchone()
        if row is None or row[0] != spec["table"] or re.sub(r"\s+", "", spec["token"]).lower() not in re.sub(r"\s+", "", row[1]).lower():
            errors.append(f"trigger:{name}")
    return errors
