"""Create user-owned FIT imports and activity data.

Revision ID: 0002_activity_import
Revises: 0001_backend_foundation
Create Date: 2026-07-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_activity_import"
down_revision: str | None = "0001_backend_foundation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _owner_activity_fk(name: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["activity_id", "user_id"],
        ["activities.id", "activities.user_id"],
        ondelete="CASCADE",
        name=name,
    )


def upgrade() -> None:
    op.create_table(
        "activity_imports",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=100), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("storage_key", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("parser_name", sa.String(length=80), nullable=False),
        sa.Column("parser_version", sa.String(length=40), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("error_message", sa.String(length=240), nullable=True),
        sa.Column("warning_count", sa.Integer(), nullable=False),
        sa.Column("replay_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "user_id", name="uq_activity_imports_id_user"),
        sa.UniqueConstraint("storage_key", name="uq_activity_imports_storage_key"),
        sa.UniqueConstraint("user_id", "sha256", name="uq_activity_imports_user_sha256"),
    )
    op.create_index(
        "ix_activity_imports_user_created",
        "activity_imports",
        ["user_id", "created_at"],
        unique=False,
    )

    op.create_table(
        "activities",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_import_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("sport", sa.String(length=80), nullable=False),
        sa.Column("sub_sport", sa.String(length=80), nullable=False),
        sa.Column("profile", sa.String(length=20), nullable=False),
        sa.Column("start_time_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("local_start_time", sa.DateTime(timezone=False), nullable=True),
        sa.Column("utc_offset_minutes", sa.SmallInteger(), nullable=True),
        sa.Column("total_timer_time_sec", sa.Float(), nullable=False),
        sa.Column("total_elapsed_time_sec", sa.Float(), nullable=False),
        sa.Column("total_distance_m", sa.Float(), nullable=False),
        sa.Column("avg_hr", sa.SmallInteger(), nullable=True),
        sa.Column("max_hr", sa.SmallInteger(), nullable=True),
        sa.Column("total_calories", sa.Integer(), nullable=True),
        sa.Column("avg_power_w", sa.Float(), nullable=True),
        sa.Column("max_power_w", sa.Float(), nullable=True),
        sa.Column("normalized_power_w", sa.Float(), nullable=True),
        sa.Column("total_ascent_m", sa.Float(), nullable=True),
        sa.Column("total_descent_m", sa.Float(), nullable=True),
        sa.Column("avg_speed_mps", sa.Float(), nullable=True),
        sa.Column("max_speed_mps", sa.Float(), nullable=True),
        sa.Column("avg_cadence_spm", sa.Float(), nullable=True),
        sa.Column("total_training_effect", sa.Float(), nullable=True),
        sa.Column("total_anaerobic_training_effect", sa.Float(), nullable=True),
        sa.Column("avg_temperature_c", sa.Float(), nullable=True),
        sa.Column("max_temperature_c", sa.Float(), nullable=True),
        sa.Column("min_temperature_c", sa.Float(), nullable=True),
        sa.Column("avg_gct_ms", sa.Float(), nullable=True),
        sa.Column("avg_vert_osc_mm", sa.Float(), nullable=True),
        sa.Column("avg_vertical_ratio", sa.Float(), nullable=True),
        sa.Column("avg_step_length_mm", sa.Float(), nullable=True),
        sa.Column("workout_feel", sa.Float(), nullable=True),
        sa.Column("workout_rpe", sa.Float(), nullable=True),
        sa.Column("extra_metrics", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["source_import_id", "user_id"],
            ["activity_imports.id", "activity_imports.user_id"],
            ondelete="CASCADE",
            name="fk_activities_import_owner",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "user_id", name="uq_activities_id_user"),
        sa.UniqueConstraint("source_import_id", name="uq_activities_source_import_id"),
    )
    op.create_index(
        "ix_activities_user_profile", "activities", ["user_id", "profile"], unique=False
    )
    op.create_index(
        "ix_activities_user_start",
        "activities",
        ["user_id", "start_time_utc", "id"],
        unique=False,
    )

    op.create_table(
        "activity_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("activity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("message_index", sa.Integer(), nullable=False),
        sa.Column("sport", sa.String(length=80), nullable=False),
        sa.Column("sub_sport", sa.String(length=80), nullable=False),
        sa.Column("start_time_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("summary", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        _owner_activity_fk("fk_activity_sessions_activity_owner"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("activity_id", "message_index", name="uq_activity_sessions_index"),
    )
    op.create_index(
        "ix_activity_sessions_user_activity",
        "activity_sessions",
        ["user_id", "activity_id"],
        unique=False,
    )

    op.create_table(
        "activity_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("activity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("elapsed_sec", sa.Float(), nullable=False),
        sa.Column("distance_m", sa.Float(), nullable=True),
        sa.Column("speed_mps", sa.Float(), nullable=True),
        sa.Column("heart_rate", sa.SmallInteger(), nullable=True),
        sa.Column("power_w", sa.Float(), nullable=True),
        sa.Column("cadence_spm", sa.Float(), nullable=True),
        sa.Column("altitude_m", sa.Float(), nullable=True),
        sa.Column("temperature_c", sa.Float(), nullable=True),
        sa.Column("stance_time_ms", sa.Float(), nullable=True),
        sa.Column("vertical_oscillation_mm", sa.Float(), nullable=True),
        sa.Column("position_lat", sa.Float(), nullable=True),
        sa.Column("position_long", sa.Float(), nullable=True),
        sa.Column("extra_metrics", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        _owner_activity_fk("fk_activity_records_activity_owner"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("activity_id", "sequence", name="uq_activity_records_sequence"),
    )
    op.create_index(
        "ix_activity_records_user_activity",
        "activity_records",
        ["user_id", "activity_id", "sequence"],
        unique=False,
    )

    op.create_table(
        "activity_laps",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("activity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("message_index", sa.Integer(), nullable=False),
        sa.Column("start_time_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_sec", sa.Float(), nullable=False),
        sa.Column("distance_m", sa.Float(), nullable=False),
        sa.Column("avg_hr", sa.SmallInteger(), nullable=True),
        sa.Column("max_hr", sa.SmallInteger(), nullable=True),
        sa.Column("avg_power_w", sa.Float(), nullable=True),
        sa.Column("avg_speed_mps", sa.Float(), nullable=True),
        sa.Column("extra_metrics", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        _owner_activity_fk("fk_activity_laps_activity_owner"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("activity_id", "message_index", name="uq_activity_laps_index"),
    )
    op.create_index(
        "ix_activity_laps_user_activity",
        "activity_laps",
        ["user_id", "activity_id"],
        unique=False,
    )

    op.create_table(
        "activity_segments",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("activity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=80), nullable=False),
        sa.Column("label", sa.String(length=255), nullable=True),
        sa.Column("start_time_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_sec", sa.Float(), nullable=True),
        sa.Column("repetitions", sa.Float(), nullable=True),
        sa.Column("weight_kg", sa.Float(), nullable=True),
        sa.Column("extra_data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        _owner_activity_fk("fk_activity_segments_activity_owner"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("activity_id", "sequence", name="uq_activity_segments_sequence"),
    )
    op.create_index(
        "ix_activity_segments_user_activity",
        "activity_segments",
        ["user_id", "activity_id"],
        unique=False,
    )

    op.create_table(
        "activity_devices",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("activity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("message_index", sa.Integer(), nullable=False),
        sa.Column("device_role", sa.String(length=80), nullable=False),
        sa.Column("manufacturer", sa.String(length=120), nullable=True),
        sa.Column("product", sa.String(length=120), nullable=True),
        sa.Column("display_name", sa.String(length=160), nullable=True),
        sa.Column("transport", sa.String(length=80), nullable=True),
        sa.Column("source_type", sa.String(length=80), nullable=True),
        sa.Column("software_version", sa.String(length=80), nullable=True),
        sa.Column("battery_status", sa.String(length=80), nullable=True),
        sa.Column("serial_number_hash", sa.String(length=64), nullable=True),
        sa.Column("raw_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        _owner_activity_fk("fk_activity_devices_activity_owner"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "user_id", name="uq_activity_devices_id_user"),
        sa.UniqueConstraint("activity_id", "message_index", name="uq_activity_devices_index"),
    )
    op.create_index(
        "ix_activity_devices_user_activity",
        "activity_devices",
        ["user_id", "activity_id"],
        unique=False,
    )

    op.create_table(
        "activity_metric_definitions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("activity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("device_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("stable_key", sa.String(length=180), nullable=False),
        sa.Column("message_name", sa.String(length=80), nullable=True),
        sa.Column("field_name", sa.String(length=160), nullable=True),
        sa.Column("unit", sa.String(length=80), nullable=True),
        sa.Column("value_type", sa.String(length=80), nullable=True),
        sa.Column("native_message_number", sa.Integer(), nullable=True),
        sa.Column("developer_data_index", sa.Integer(), nullable=True),
        sa.Column("field_definition_number", sa.Integer(), nullable=True),
        sa.Column("application_id_hash", sa.String(length=64), nullable=True),
        _owner_activity_fk("fk_activity_metric_definitions_activity_owner"),
        sa.ForeignKeyConstraint(
            ["device_id", "user_id"],
            ["activity_devices.id", "activity_devices.user_id"],
            name="fk_activity_metric_definitions_device_owner",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("activity_id", "stable_key", name="uq_activity_metric_definitions_key"),
    )
    op.create_index(
        "ix_activity_metric_definitions_user_activity",
        "activity_metric_definitions",
        ["user_id", "activity_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_activity_metric_definitions_user_activity",
        table_name="activity_metric_definitions",
    )
    op.drop_table("activity_metric_definitions")
    op.drop_index("ix_activity_devices_user_activity", table_name="activity_devices")
    op.drop_table("activity_devices")
    op.drop_index("ix_activity_segments_user_activity", table_name="activity_segments")
    op.drop_table("activity_segments")
    op.drop_index("ix_activity_laps_user_activity", table_name="activity_laps")
    op.drop_table("activity_laps")
    op.drop_index("ix_activity_records_user_activity", table_name="activity_records")
    op.drop_table("activity_records")
    op.drop_index("ix_activity_sessions_user_activity", table_name="activity_sessions")
    op.drop_table("activity_sessions")
    op.drop_index("ix_activities_user_start", table_name="activities")
    op.drop_index("ix_activities_user_profile", table_name="activities")
    op.drop_table("activities")
    op.drop_index("ix_activity_imports_user_created", table_name="activity_imports")
    op.drop_table("activity_imports")
