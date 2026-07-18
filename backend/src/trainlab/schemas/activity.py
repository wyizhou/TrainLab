import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ActivityListItem(BaseModel):
    id: uuid.UUID
    date: str
    type: str
    name: str
    distance_km: float | None = Field(serialization_alias="distanceKm")
    duration_sec: int = Field(serialization_alias="durationSec")
    avg_hr: int | None = Field(serialization_alias="avgHr")
    pace_sec_per_km: int | None = Field(serialization_alias="paceSecPerKm")
    pace_100_sec: int | None = Field(serialization_alias="pace100Sec")
    power_w: int | None = Field(serialization_alias="powerW")
    source: str
    profile: str
    parse_status: str = Field(serialization_alias="parseStatus")
    original_file_name: str = Field(serialization_alias="originalFileName")


class ActivityListPage(BaseModel):
    items: list[ActivityListItem]
    next_cursor: str | None = Field(serialization_alias="nextCursor")


class FitImportResponse(BaseModel):
    import_id: uuid.UUID = Field(serialization_alias="importId")
    status: Literal["complete", "partial"]
    deduplicated: bool
    activity: ActivityListItem
    retry_available: bool = Field(serialization_alias="retryAvailable")


class ActivitySummaryResponse(BaseModel):
    sport: str
    sub_sport: str = Field(serialization_alias="subSport")
    start_time: datetime = Field(serialization_alias="startTime")
    local_start_time: datetime | None = Field(serialization_alias="localStartTime")
    utc_offset_minutes: int | None = Field(serialization_alias="utcOffsetMinutes")
    total_timer_time_sec: float = Field(serialization_alias="totalTimerTimeSec")
    total_elapsed_time_sec: float = Field(serialization_alias="totalElapsedTimeSec")
    total_distance_m: float = Field(serialization_alias="totalDistanceM")
    avg_hr: int | None = Field(serialization_alias="avgHr")
    max_hr: int | None = Field(serialization_alias="maxHr")
    total_calories: int | None = Field(serialization_alias="totalCalories")
    avg_power_w: float | None = Field(serialization_alias="avgPowerW")
    max_power_w: float | None = Field(serialization_alias="maxPowerW")
    normalized_power_w: float | None = Field(serialization_alias="normalizedPowerW")
    total_ascent_m: float | None = Field(serialization_alias="totalAscentM")
    total_descent_m: float | None = Field(serialization_alias="totalDescentM")
    avg_speed_mps: float | None = Field(serialization_alias="avgSpeedMps")
    max_speed_mps: float | None = Field(serialization_alias="maxSpeedMps")
    avg_cadence_spm: float | None = Field(serialization_alias="avgCadenceSpm")
    total_training_effect: float | None = Field(serialization_alias="totalTrainingEffect")
    total_anaerobic_training_effect: float | None = Field(
        serialization_alias="totalAnaerobicTrainingEffect"
    )
    avg_temperature_c: float | None = Field(serialization_alias="avgTemperatureC")
    max_temperature_c: float | None = Field(serialization_alias="maxTemperatureC")
    min_temperature_c: float | None = Field(serialization_alias="minTemperatureC")
    avg_gct_ms: float | None = Field(serialization_alias="avgGctMs")
    avg_vert_osc_mm: float | None = Field(serialization_alias="avgVertOscMm")
    avg_vertical_ratio: float | None = Field(serialization_alias="avgVerticalRatio")
    avg_step_length_mm: float | None = Field(serialization_alias="avgStepLengthMm")
    workout_feel: float | None = Field(serialization_alias="workoutFeel")
    workout_rpe: float | None = Field(serialization_alias="workoutRpe")
    extra_metrics: dict[str, Any] = Field(serialization_alias="extraMetrics")


class ActivityRecordResponse(BaseModel):
    sequence: int
    timestamp: datetime | None
    t_sec: float = Field(serialization_alias="tSec")
    distance_m: float | None = Field(serialization_alias="distanceM")
    speed_mps: float | None = Field(serialization_alias="speedMps")
    pace_sec_per_km: float | None = Field(serialization_alias="paceSecPerKm")
    hr: int | None
    power_w: float | None = Field(serialization_alias="powerW")
    cadence_spm: float | None = Field(serialization_alias="cadenceSpm")
    altitude_m: float | None = Field(serialization_alias="altitudeM")
    temperature_c: float | None = Field(serialization_alias="temperatureC")
    gct_ms: float | None = Field(serialization_alias="gctMs")
    vert_osc_mm: float | None = Field(serialization_alias="vertOscMm")
    position_lat: float | None = Field(serialization_alias="positionLat")
    position_long: float | None = Field(serialization_alias="positionLong")
    extra_metrics: dict[str, Any] = Field(serialization_alias="extraMetrics")


class ActivityLapResponse(BaseModel):
    index: int
    start_time: datetime | None = Field(serialization_alias="startTime")
    distance_m: float = Field(serialization_alias="distanceM")
    duration_sec: float = Field(serialization_alias="durationSec")
    avg_hr: int | None = Field(serialization_alias="avgHr")
    max_hr: int | None = Field(serialization_alias="maxHr")
    avg_pace_sec_per_km: float | None = Field(serialization_alias="avgPaceSecPerKm")
    avg_power_w: float | None = Field(serialization_alias="avgPowerW")
    extra_metrics: dict[str, Any] = Field(serialization_alias="extraMetrics")


class ActivitySegmentExerciseSemantic(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    step_index: int = Field(alias="stepIndex")
    name: str


class ActivitySegmentClimbSemantic(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    grade_status: Literal["available", "unavailable"] = Field(alias="gradeStatus")
    grade_reason: Literal["unknown_profile_field"] | None = Field(default=None, alias="gradeReason")
    grade_system: Literal["v_scale", "yds"] | None = Field(default=None, alias="gradeSystem")
    grade: str | None = None
    outcome: Literal["complete", "attempt", "unknown"] | None = None


class ActivitySegmentSemantic(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    schema_version: Literal[1] = Field(alias="schemaVersion")
    source_message: Literal["set", "split", "split_summary"] = Field(alias="sourceMessage")
    exercise: ActivitySegmentExerciseSemantic | None = None
    climb: ActivitySegmentClimbSemantic | None = None


class ActivitySegmentResponse(BaseModel):
    sequence: int
    kind: str
    label: str | None
    start_time: datetime | None = Field(serialization_alias="startTime")
    duration_sec: float | None = Field(serialization_alias="durationSec")
    repetitions: float | None
    weight_kg: float | None = Field(serialization_alias="weightKg")
    extra_data: dict[str, Any] = Field(serialization_alias="extraData")
    semantic: ActivitySegmentSemantic | None = None


class ActivityDeviceResponse(BaseModel):
    id: uuid.UUID
    role: str
    manufacturer: str | None
    product: str | None
    display_name: str | None = Field(serialization_alias="displayName")
    transport: str | None
    source_type: str | None = Field(serialization_alias="sourceType")
    software_version: str | None = Field(serialization_alias="softwareVersion")
    battery_status: str | None = Field(serialization_alias="batteryStatus")


class ActivityMetricDefinitionResponse(BaseModel):
    id: uuid.UUID
    device_id: uuid.UUID | None = Field(serialization_alias="deviceId")
    stable_key: str = Field(serialization_alias="stableKey")
    message_name: str | None = Field(serialization_alias="messageName")
    field_name: str | None = Field(serialization_alias="fieldName")
    unit: str | None
    value_type: str | None = Field(serialization_alias="valueType")
    native_message_number: int | None = Field(serialization_alias="nativeMessageNumber")
    developer_data_index: int | None = Field(serialization_alias="developerDataIndex")
    field_definition_number: int | None = Field(serialization_alias="fieldDefinitionNumber")


class ActivitySessionResponse(BaseModel):
    message_index: int = Field(serialization_alias="messageIndex")
    sport: str
    sub_sport: str = Field(serialization_alias="subSport")
    start_time: datetime | None = Field(serialization_alias="startTime")


class ActivityDetailResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    activity: ActivityListItem
    summary: ActivitySummaryResponse
    sessions: list[ActivitySessionResponse]
    records: list[ActivityRecordResponse]
    record_count: int = Field(serialization_alias="recordCount")
    records_sampled: bool = Field(serialization_alias="recordsSampled")
    laps: list[ActivityLapResponse]
    segments: list[ActivitySegmentResponse]
    devices: list[ActivityDeviceResponse]
    metric_definitions: list[ActivityMetricDefinitionResponse] = Field(
        serialization_alias="metricDefinitions"
    )
    parse_status: str = Field(serialization_alias="parseStatus")
    warning_count: int = Field(serialization_alias="warningCount")
    download_available: bool = Field(serialization_alias="downloadAvailable")
    original_file_name: str = Field(serialization_alias="originalFileName")
