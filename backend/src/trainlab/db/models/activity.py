import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    SmallInteger,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from trainlab.db.base import Base, TimestampMixin


class ActivityImport(TimestampMixin, Base):
    __tablename__ = "activity_imports"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="fit_upload")
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    parser_name: Mapped[str] = mapped_column(String(80), nullable=False)
    parser_version: Mapped[str] = mapped_column(String(40), nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(240), nullable=True)
    warning_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    title_override: Mapped[str | None] = mapped_column(String(255), nullable=True)
    delete_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_delete_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    delete_attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    delete_error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    processing_token: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    replay_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    __table_args__ = (
        UniqueConstraint("user_id", "sha256", name="uq_activity_imports_user_sha256"),
        UniqueConstraint("id", "user_id", name="uq_activity_imports_id_user"),
        Index("ix_activity_imports_user_created", "user_id", "created_at"),
        Index("ix_activity_imports_user_status_created", "user_id", "status", "created_at"),
    )


class Activity(TimestampMixin, Base):
    __tablename__ = "activities"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    source_import_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, unique=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    sport: Mapped[str] = mapped_column(String(80), nullable=False)
    sub_sport: Mapped[str] = mapped_column(String(80), nullable=False)
    profile: Mapped[str] = mapped_column(String(20), nullable=False)
    start_time_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    local_start_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True
    )
    utc_offset_minutes: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    total_timer_time_sec: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    total_elapsed_time_sec: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    total_distance_m: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    avg_hr: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    max_hr: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    total_calories: Mapped[int | None] = mapped_column(Integer, nullable=True)
    avg_power_w: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_power_w: Mapped[float | None] = mapped_column(Float, nullable=True)
    normalized_power_w: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_ascent_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_descent_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_speed_mps: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_speed_mps: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_cadence_spm: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_training_effect: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_anaerobic_training_effect: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_temperature_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_temperature_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    min_temperature_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_gct_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_vert_osc_mm: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_vertical_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_step_length_mm: Mapped[float | None] = mapped_column(Float, nullable=True)
    workout_feel: Mapped[float | None] = mapped_column(Float, nullable=True)
    workout_rpe: Mapped[float | None] = mapped_column(Float, nullable=True)
    extra_metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    __table_args__ = (
        UniqueConstraint("id", "user_id", name="uq_activities_id_user"),
        ForeignKeyConstraint(
            ["source_import_id", "user_id"],
            ["activity_imports.id", "activity_imports.user_id"],
            ondelete="CASCADE",
            name="fk_activities_import_owner",
        ),
        Index("ix_activities_user_start", "user_id", "start_time_utc", "id"),
        Index("ix_activities_user_profile", "user_id", "profile"),
    )


class ActivitySession(Base):
    __tablename__ = "activity_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    activity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    message_index: Mapped[int] = mapped_column(Integer, nullable=False)
    sport: Mapped[str] = mapped_column(String(80), nullable=False)
    sub_sport: Mapped[str] = mapped_column(String(80), nullable=False)
    start_time_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    summary: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    __table_args__ = (
        ForeignKeyConstraint(
            ["activity_id", "user_id"],
            ["activities.id", "activities.user_id"],
            ondelete="CASCADE",
            name="fk_activity_sessions_activity_owner",
        ),
        UniqueConstraint("activity_id", "message_index", name="uq_activity_sessions_index"),
        Index("ix_activity_sessions_user_activity", "user_id", "activity_id"),
    )


class ActivityRecord(Base):
    __tablename__ = "activity_records"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    activity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    elapsed_sec: Mapped[float] = mapped_column(Float, nullable=False)
    distance_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    speed_mps: Mapped[float | None] = mapped_column(Float, nullable=True)
    heart_rate: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    power_w: Mapped[float | None] = mapped_column(Float, nullable=True)
    cadence_spm: Mapped[float | None] = mapped_column(Float, nullable=True)
    altitude_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    temperature_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    stance_time_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    vertical_oscillation_mm: Mapped[float | None] = mapped_column(Float, nullable=True)
    position_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    position_long: Mapped[float | None] = mapped_column(Float, nullable=True)
    extra_metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    __table_args__ = (
        ForeignKeyConstraint(
            ["activity_id", "user_id"],
            ["activities.id", "activities.user_id"],
            ondelete="CASCADE",
            name="fk_activity_records_activity_owner",
        ),
        UniqueConstraint("activity_id", "sequence", name="uq_activity_records_sequence"),
        Index("ix_activity_records_user_activity", "user_id", "activity_id", "sequence"),
    )


class ActivityLap(Base):
    __tablename__ = "activity_laps"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    activity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    message_index: Mapped[int] = mapped_column(Integer, nullable=False)
    start_time_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_sec: Mapped[float] = mapped_column(Float, nullable=False)
    distance_m: Mapped[float] = mapped_column(Float, nullable=False)
    avg_hr: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    max_hr: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    avg_power_w: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_speed_mps: Mapped[float | None] = mapped_column(Float, nullable=True)
    extra_metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    __table_args__ = (
        ForeignKeyConstraint(
            ["activity_id", "user_id"],
            ["activities.id", "activities.user_id"],
            ondelete="CASCADE",
            name="fk_activity_laps_activity_owner",
        ),
        UniqueConstraint("activity_id", "message_index", name="uq_activity_laps_index"),
        Index("ix_activity_laps_user_activity", "user_id", "activity_id"),
    )


class ActivitySegment(Base):
    __tablename__ = "activity_segments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    activity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(80), nullable=False)
    label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    start_time_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_sec: Mapped[float | None] = mapped_column(Float, nullable=True)
    repetitions: Mapped[float | None] = mapped_column(Float, nullable=True)
    weight_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    extra_data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    __table_args__ = (
        ForeignKeyConstraint(
            ["activity_id", "user_id"],
            ["activities.id", "activities.user_id"],
            ondelete="CASCADE",
            name="fk_activity_segments_activity_owner",
        ),
        UniqueConstraint("activity_id", "sequence", name="uq_activity_segments_sequence"),
        Index("ix_activity_segments_user_activity", "user_id", "activity_id"),
    )


class ActivityDevice(Base):
    __tablename__ = "activity_devices"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    activity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    message_index: Mapped[int] = mapped_column(Integer, nullable=False)
    device_role: Mapped[str] = mapped_column(String(80), nullable=False)
    manufacturer: Mapped[str | None] = mapped_column(String(120), nullable=True)
    product: Mapped[str | None] = mapped_column(String(120), nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    transport: Mapped[str | None] = mapped_column(String(80), nullable=True)
    source_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    software_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    battery_status: Mapped[str | None] = mapped_column(String(80), nullable=True)
    serial_number_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    raw_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    __table_args__ = (
        UniqueConstraint("id", "user_id", name="uq_activity_devices_id_user"),
        ForeignKeyConstraint(
            ["activity_id", "user_id"],
            ["activities.id", "activities.user_id"],
            ondelete="CASCADE",
            name="fk_activity_devices_activity_owner",
        ),
        UniqueConstraint("activity_id", "message_index", name="uq_activity_devices_index"),
        Index("ix_activity_devices_user_activity", "user_id", "activity_id"),
    )


class ActivityMetricDefinition(Base):
    __tablename__ = "activity_metric_definitions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    activity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    device_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    stable_key: Mapped[str] = mapped_column(String(180), nullable=False)
    message_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    field_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    unit: Mapped[str | None] = mapped_column(String(80), nullable=True)
    value_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    native_message_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    developer_data_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    field_definition_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    application_id_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["activity_id", "user_id"],
            ["activities.id", "activities.user_id"],
            ondelete="CASCADE",
            name="fk_activity_metric_definitions_activity_owner",
        ),
        ForeignKeyConstraint(
            ["device_id", "user_id"],
            ["activity_devices.id", "activity_devices.user_id"],
            name="fk_activity_metric_definitions_device_owner",
        ),
        UniqueConstraint("activity_id", "stable_key", name="uq_activity_metric_definitions_key"),
        Index("ix_activity_metric_definitions_user_activity", "user_id", "activity_id"),
    )
