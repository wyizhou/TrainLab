"""SQLite table contracts for B0 and later ADHOC-0024..0028 implementation."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ColumnContract:
    name: str
    sql_type: str
    nullable: bool
    purpose: str


@dataclass(frozen=True)
class TableContract:
    name: str
    columns: tuple[ColumnContract, ...]
    business_table: bool
    ddl: str

    @property
    def column_names(self) -> tuple[str, ...]:
        return tuple(column.name for column in self.columns)


ACTIVITIES_COLUMNS = (
    ColumnContract("activity_id", "TEXT", False, "FIT actual bytes SHA-256 primary key"),
    ColumnContract("fit_path", "TEXT", False, "Repository-instance relative path for host use"),
    ColumnContract("sport", "TEXT", True, "FIT session sport"),
    ColumnContract("sub_sport", "TEXT", True, "FIT session sub sport"),
    ColumnContract("start_time_utc", "TEXT", True, "Confirmed activity start time in UTC"),
    ColumnContract("end_time_utc", "TEXT", True, "Confirmed activity end time in UTC"),
    ColumnContract("schema_version", "INTEGER", False, "Storage schema version"),
    ColumnContract("parsed_at_utc", "TEXT", False, "Successful parse time in UTC"),
    ColumnContract("basic_json", "TEXT", False, "Default AI class 1 facts as JSON"),
    ColumnContract("summary_json", "TEXT", False, "FIT factual whole-activity summary JSON"),
    ColumnContract("segments_json", "TEXT", False, "Native lap/split/set segments JSON"),
    ColumnContract("sensors_json", "TEXT", False, "Device and field definition JSON, not record body"),
)

RECORDS_COLUMNS = (
    ColumnContract("activity_id", "TEXT", False, "Parent activity id"),
    ColumnContract("record_index", "INTEGER", False, "Original FIT record order from zero"),
    ColumnContract("timestamp_utc", "TEXT", True, "Record timestamp in UTC if known"),
    ColumnContract("metrics_json", "TEXT", False, "Record metrics JSON"),
)

ACTIVTIES_REPORT_COLUMNS = (
    ColumnContract("activity_id", "TEXT", False, "Reported activity id"),
    ColumnContract("start_time_utc", "TEXT", True, "Activity start time, not generation time"),
    ColumnContract("summary", "TEXT", False, "Full AI activity summary text"),
)

WEEKLY_REPORT_COLUMNS = (
    ColumnContract("id", "INTEGER", False, "SQLite autoincrement report identity"),
    ColumnContract("run_time_utc", "TEXT", False, "Actual run time T in UTC"),
    ColumnContract("summary", "TEXT", False, "Full AI weekly summary text"),
)

CONFIG_COLUMNS = (
    ColumnContract("key", "TEXT", False, "System parameter name"),
    ColumnContract("value_json", "TEXT", False, "System parameter JSON value"),
    ColumnContract("updated_at_utc", "TEXT", False, "Configuration update time in UTC"),
)

ACTIVITIES = TableContract(
    name="activities",
    columns=ACTIVITIES_COLUMNS,
    business_table=True,
    ddl="""
CREATE TABLE IF NOT EXISTS activities (
    activity_id TEXT PRIMARY KEY NOT NULL,
    fit_path TEXT NOT NULL,
    sport TEXT,
    sub_sport TEXT,
    start_time_utc TEXT,
    end_time_utc TEXT,
    schema_version INTEGER NOT NULL,
    parsed_at_utc TEXT NOT NULL,
    basic_json TEXT NOT NULL,
    summary_json TEXT NOT NULL,
    segments_json TEXT NOT NULL,
    sensors_json TEXT NOT NULL
)
""".strip(),
)

RECORDS = TableContract(
    name="records",
    columns=RECORDS_COLUMNS,
    business_table=True,
    ddl="""
CREATE TABLE IF NOT EXISTS records (
    activity_id TEXT NOT NULL,
    record_index INTEGER NOT NULL,
    timestamp_utc TEXT,
    metrics_json TEXT NOT NULL,
    PRIMARY KEY (activity_id, record_index),
    FOREIGN KEY (activity_id) REFERENCES activities(activity_id)
)
""".strip(),
)

ACTIVTIES_REPORT = TableContract(
    name="activties_report",
    columns=ACTIVTIES_REPORT_COLUMNS,
    business_table=True,
    ddl="""
CREATE TABLE IF NOT EXISTS activties_report (
    activity_id TEXT PRIMARY KEY NOT NULL,
    start_time_utc TEXT,
    summary TEXT NOT NULL,
    FOREIGN KEY (activity_id) REFERENCES activities(activity_id)
)
""".strip(),
)

WEEKLY_REPORT = TableContract(
    name="weekly_report",
    columns=WEEKLY_REPORT_COLUMNS,
    business_table=True,
    ddl="""
CREATE TABLE IF NOT EXISTS weekly_report (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_time_utc TEXT NOT NULL,
    summary TEXT NOT NULL
)
""".strip(),
)

CONFIG = TableContract(
    name="config",
    columns=CONFIG_COLUMNS,
    business_table=False,
    ddl="""
CREATE TABLE IF NOT EXISTS config (
    key TEXT PRIMARY KEY NOT NULL,
    value_json TEXT NOT NULL,
    updated_at_utc TEXT NOT NULL
)
""".strip(),
)

BUSINESS_TABLES = ("activities", "records", "activties_report", "weekly_report")
SYSTEM_TABLES = ("config",)


def table_contracts(include_system: bool = True) -> tuple[TableContract, ...]:
    business = (ACTIVITIES, RECORDS, ACTIVTIES_REPORT, WEEKLY_REPORT)
    if not include_system:
        return business
    return business + (CONFIG,)


def ddl_statements(include_system: bool = True) -> tuple[str, ...]:
    return tuple(table.ddl for table in table_contracts(include_system=include_system))
