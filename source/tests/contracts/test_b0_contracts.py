from __future__ import annotations

import importlib.util
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from types import ModuleType

from fastapi.testclient import TestClient

from trainlab.contracts.config import public_config_contracts
from trainlab.contracts.errors import ErrorCode, failure_envelope, http_status_for_error
from trainlab.contracts.interfaces import (
    JSON_SCHEMA_CONTRACTS,
    REFERENCE_CONTRACTS,
    TOOL_CONTRACTS,
    UNCONFIGURED_POLICIES,
    CapacityPolicy,
    PendingDecision,
    ToolAuthorization,
    validate_payload,
    validate_schema_examples,
)
from trainlab.contracts.paths import (
    AI_CONFIG_PATH,
    WEB_STATIC_DIR,
    activity_fit_name,
    ai_config_reference,
    validate_static_mount,
)
from trainlab.contracts.schema import (
    BUSINESS_TABLES,
    SYSTEM_TABLES,
    ddl_statements,
    table_contracts,
)
from trainlab.contracts.session import InMemoryConversationHistory
from trainlab.contracts.time import (
    NO_ACTIVITY_WEEKLY_SUMMARY,
    ensure_utc,
    format_utc,
    initial_sync_window,
    next_activity_report_run_utc,
    utc_fit_date,
    weekly_window,
)
from trainlab.contracts.web import route_paths, static_mount_dir


@contextmanager
def chdir(path: Path) -> Iterator[None]:
    old_cwd = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(old_cwd)


def naive_datetime() -> datetime:
    return datetime(2026, 9, 16, 0, 0)  # noqa: DTZ001


def load_server_module() -> ModuleType:
    source_root = Path(__file__).resolve().parents[2]
    server_path = source_root / "skills/local-web/scripts/server.py"
    spec = importlib.util.spec_from_file_location("trainlab_local_web_server", server_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load server module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def create_schema_database() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.execute("PRAGMA foreign_keys = ON")
    for statement in ddl_statements():
        connection.execute(statement)
    return connection


class B0ContractTests(unittest.TestCase):
    def test_ai_config_contract_references_private_path_without_secret_values_or_key_freeze(self) -> None:
        ref = ai_config_reference().to_json()
        self.assertEqual(ref["path"], "states/ai.json")
        self.assertEqual(AI_CONFIG_PATH, Path("states/ai.json"))
        public = json.dumps(public_config_contracts(), ensure_ascii=False)
        self.assertIn("openai_compatible_base_url", public)
        self.assertIn('"exact_private_key_names_frozen": false', public)
        self.assertNotIn("sk-", public)

    def test_first_sync_window_and_fit_sha_name_contract(self) -> None:
        now = datetime(2026, 9, 16, 12, 0, tzinfo=UTC)
        start, end = initial_sync_window(now)
        self.assertEqual((end - start).days, 7)
        self.assertEqual(activity_fit_name(utc_fit_date(now), "a" * 64), f"20260916-{'a' * 64}.fit")
        self.assertEqual(activity_fit_name(None, "b" * 64), f"unknown-{'b' * 64}.fit")
        with self.assertRaises(ValueError):
            activity_fit_name("2026-09-16", "c" * 64)
        with self.assertRaises(ValueError):
            activity_fit_name("２０２６０９１６", "c" * 64)

    def test_time_contract_rejects_naive_and_formats_utc(self) -> None:
        aware = datetime(2026, 9, 16, 8, 30, tzinfo=timezone(timedelta(hours=8)))
        self.assertEqual(ensure_utc(aware), datetime(2026, 9, 16, 0, 30, tzinfo=UTC))
        self.assertEqual(format_utc(aware), "2026-09-16T00:30:00.000000Z")
        with self.assertRaises(ValueError):
            ensure_utc(naive_datetime())

    def test_activity_report_runs_at_next_china_4am(self) -> None:
        before = datetime(2026, 9, 15, 19, 30, tzinfo=UTC)
        self.assertEqual(next_activity_report_run_utc(before), datetime(2026, 9, 15, 20, 0, tzinfo=UTC))
        after = datetime(2026, 9, 15, 20, 1, tzinfo=UTC)
        self.assertEqual(next_activity_report_run_utc(after), datetime(2026, 9, 16, 20, 0, tzinfo=UTC))

    def test_weekly_window_and_no_activity_text_contract(self) -> None:
        run_time = datetime(2026, 9, 16, 3, 4, 5, tzinfo=UTC)
        start, end = weekly_window(run_time)
        self.assertEqual(end, run_time)
        self.assertEqual((end - start).days, 7)
        self.assertEqual(NO_ACTIVITY_WEEKLY_SUMMARY, "本周无任何运动记录")

    def test_schema_business_tables_and_config_system_table(self) -> None:
        contracts = {table.name: table for table in table_contracts()}
        self.assertEqual(BUSINESS_TABLES, ("activities", "records", "activties_report", "weekly_report"))
        self.assertEqual(SYSTEM_TABLES, ("config",))
        self.assertEqual(len(contracts["activities"].columns), 12)
        self.assertEqual(len(contracts["records"].columns), 4)
        self.assertEqual(len(contracts["activties_report"].columns), 3)
        self.assertEqual(len(contracts["weekly_report"].columns), 3)
        self.assertEqual(contracts["config"].business_table, False)
        self.assertEqual(contracts["config"].column_names, ("key", "value_json", "updated_at_utc"))

    def test_schema_ddl_builds_and_preserves_normal_relations(self) -> None:
        connection = create_schema_database()
        try:
            rows = connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()
            connection.execute(
                """
                INSERT INTO activities VALUES(
                  ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                (
                    "a" * 64,
                    "states/activities/20260916-a.fit",
                    "running",
                    None,
                    "2026-09-16T00:00:00.000000Z",
                    "2026-09-16T01:00:00.000000Z",
                    1,
                    "2026-09-16T02:00:00.000000Z",
                    "{}",
                    "{}",
                    "[]",
                    "{}",
                ),
            )
            connection.executemany(
                "INSERT INTO records VALUES(?, ?, ?, ?)",
                [
                    ("a" * 64, 1, "2026-09-16T00:00:02.000000Z", "{}"),
                    ("a" * 64, 0, "2026-09-16T00:00:02.000000Z", "{}"),
                ],
            )
            ordered = connection.execute(
                "SELECT record_index FROM records WHERE activity_id=? ORDER BY record_index",
                ("a" * 64,),
            ).fetchall()
            connection.execute("INSERT INTO activties_report VALUES(?, ?, ?)", ("a" * 64, None, "全文"))
            connection.execute(
                "INSERT INTO weekly_report(run_time_utc, summary) VALUES(?, ?)",
                ("2026-09-16T02:00:00.000000Z", "本周无任何运动记录"),
            )
            connection.execute("INSERT INTO config VALUES(?, ?, ?)", ("sync.interval", "{}", "2026-09-16T02:00:00.000000Z"))
        finally:
            connection.close()
        names = {row[0] for row in rows}
        self.assertTrue(set(BUSINESS_TABLES).issubset(names))
        self.assertIn("config", names)
        self.assertEqual(ordered, [(0,), (1,)])

    def test_schema_rejects_null_duplicate_and_orphan_keys(self) -> None:
        connection = create_schema_database()
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "INSERT INTO config VALUES(NULL, '{}', '2026-09-16T00:00:00.000000Z')"
                )
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    """
                    INSERT INTO activities VALUES(
                      NULL, 'x.fit', NULL, NULL, NULL, NULL, 1, '2026-09-16T00:00:00.000000Z', '{}', '{}', '[]', '{}'
                    )
                    """
                )
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("INSERT INTO activties_report VALUES(NULL, NULL, 'summary')")
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("INSERT INTO records VALUES(?, 0, NULL, '{}')", ("missing",))
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("INSERT INTO activties_report VALUES(?, NULL, 'summary')", ("missing",))
        finally:
            connection.close()

    def test_schema_rejects_duplicate_records_and_protects_children(self) -> None:
        connection = create_schema_database()
        try:
            connection.execute(
                "INSERT INTO activities VALUES(?, ?, NULL, NULL, NULL, NULL, 1, ?, '{}', '{}', '[]', '{}')",
                ("a" * 64, "states/activities/20260916-a.fit", "2026-09-16T00:00:00.000000Z"),
            )
            connection.execute("INSERT INTO records VALUES(?, 0, NULL, '{}')", ("a" * 64,))
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("INSERT INTO records VALUES(?, 0, NULL, '{}')", ("a" * 64,))
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("DELETE FROM activities WHERE activity_id=?", ("a" * 64,))
        finally:
            connection.close()

    def test_conversation_history_is_memory_only_and_rejects_naive_time(self) -> None:
        history = InMemoryConversationHistory()
        history.append("user", "hello", datetime(2026, 9, 16, tzinfo=UTC))
        self.assertEqual(len(history.snapshot()), 1)
        self.assertIsNone(history.persistence_target)
        with self.assertRaises(ValueError):
            history.append("user", "naive", naive_datetime())
        history.clear()
        self.assertEqual(history.snapshot(), ())

    def test_conversation_history_naive_time_rejection_is_tz_independent(self) -> None:
        script = (
            "from datetime import datetime\n"
            "from trainlab.contracts.session import InMemoryConversationHistory\n"
            "h = InMemoryConversationHistory()\n"
            "try:\n"
            "    h.append('user', 'x', datetime(2026, 9, 16))\n"
            "except ValueError:\n"
            "    print('rejected')\n"
            "else:\n"
            "    raise SystemExit('accepted')\n"
        )
        for tz_name in ("UTC", "Asia/Shanghai"):
            env = os.environ.copy()
            env["TZ"] = tz_name
            result = subprocess.run(
                [sys.executable, "-c", script],
                check=False,
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), "rejected")

    def test_static_mount_does_not_expose_states_or_escape_root(self) -> None:
        self.assertEqual(static_mount_dir(), WEB_STATIC_DIR)
        with self.assertRaises(ValueError):
            validate_static_mount(Path("states"))
        with self.assertRaises(ValueError):
            validate_static_mount(Path("source"))
        with self.assertRaises(ValueError):
            validate_static_mount(Path("source/skills/local-web/web/../../../../states"))

    def test_real_app_serves_static_and_uses_error_envelope(self) -> None:
        server = load_server_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            web_dir = root / WEB_STATIC_DIR
            web_dir.mkdir(parents=True)
            (web_dir / "index.html").write_text("<html><body>synthetic</body></html>", encoding="utf-8")
            with chdir(root):
                app = server.create_app()
                with TestClient(app) as client:
                    health = client.get("/api/health")
                    self.assertEqual(health.status_code, 200)
                    self.assertEqual(health.json()["ok"], True)
                    static = client.get("/")
                    self.assertEqual(static.status_code, 200)
                    self.assertIn("synthetic", static.text)
                    missing = client.get("/api/missing")
                    self.assertEqual(missing.status_code, 404)
                    self.assertEqual(missing.json()["ok"], False)
                    self.assertIsNone(missing.json()["data"])

    def test_real_app_rejects_static_root_symlink_to_synthetic_states(self) -> None:
        server = load_server_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            states = root / "states"
            states.mkdir()
            (states / "ai.json").write_text('{"synthetic":"secret"}', encoding="utf-8")
            web_parent = root / WEB_STATIC_DIR.parent
            web_parent.mkdir(parents=True)
            (web_parent / WEB_STATIC_DIR.name).symlink_to(states, target_is_directory=True)
            with chdir(root):
                with self.assertRaises(ValueError):
                    validate_static_mount(WEB_STATIC_DIR)
                with self.assertRaises(ValueError):
                    server.create_app()

    def test_api_routes_are_under_api_prefix(self) -> None:
        self.assertTrue(route_paths())
        self.assertTrue(all(path.startswith("/api/") for path in route_paths()))

    def test_public_schema_examples_tools_and_unconfigured_policies_are_explicit(self) -> None:
        validate_schema_examples()
        self.assertIn("GetRunningRecordsRequest", JSON_SCHEMA_CONTRACTS)
        self.assertEqual(TOOL_CONTRACTS["get_running_records"].forbidden_parameters[0], "sql")
        self.assertEqual(REFERENCE_CONTRACTS["longdou"].relative_path, Path("references/longdou.md"))
        self.assertIn(PendingDecision.ACTIVITY_BATCH_AND_BACKFILL, UNCONFIGURED_POLICIES)
        self.assertIn(PendingDecision.WEEKLY_TRIGGER_AND_MISSING_REPORTS, UNCONFIGURED_POLICIES)
        self.assertIn(PendingDecision.RUNNING_RECORDS_QUOTA, UNCONFIGURED_POLICIES)
        with self.assertRaises(ValueError):
            validate_payload("GetRunningRecordsRequest", {"activity_id": "a" * 64, "limit": 1})

    def test_authorization_capacity_and_error_mapping_contracts(self) -> None:
        authorization = ToolAuthorization(
            allowed_activity_ids=frozenset({"a" * 64}),
            allowed_reference_ids=frozenset({"longdou"}),
        )
        self.assertTrue(authorization.can_read_records("a" * 64))
        self.assertFalse(authorization.can_read_records("b" * 64))
        self.assertTrue(authorization.can_read_reference("longdou"))
        capacity = CapacityPolicy(storage_bytes_limit=10, model_payload_bytes_limit=5)
        capacity.check_storage(10)
        with self.assertRaises(ValueError):
            capacity.check_model_payload(6)
        envelope = failure_envelope(ErrorCode.RESOURCE_LIMIT, "too large").to_json()
        self.assertEqual(envelope["ok"], False)
        self.assertIsNone(envelope["data"])
        self.assertEqual(http_status_for_error(ErrorCode.RESOURCE_LIMIT), 413)


if __name__ == "__main__":
    unittest.main()
