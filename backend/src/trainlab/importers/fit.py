import hashlib
import math
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, BinaryIO

from garmin_fit_sdk import Decoder, Stream

PARSER_NAME = "garmin-fit-sdk"
PARSER_VERSION = "21.208.0"
FIT_EPOCH = datetime(1989, 12, 31, tzinfo=UTC)


class FitDecodeFailure(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ParsedSession:
    message_index: int
    sport: str
    sub_sport: str
    start_time_utc: datetime | None
    summary: dict[str, Any]


@dataclass(frozen=True)
class ParsedRecord:
    sequence: int
    timestamp: datetime | None
    elapsed_sec: float
    distance_m: float | None
    speed_mps: float | None
    heart_rate: int | None
    power_w: float | None
    cadence_spm: float | None
    altitude_m: float | None
    temperature_c: float | None
    stance_time_ms: float | None
    vertical_oscillation_mm: float | None
    position_lat: float | None
    position_long: float | None
    extra_metrics: dict[str, Any]


@dataclass(frozen=True)
class ParsedLap:
    message_index: int
    start_time_utc: datetime | None
    duration_sec: float
    distance_m: float
    avg_hr: int | None
    max_hr: int | None
    avg_power_w: float | None
    avg_speed_mps: float | None
    extra_metrics: dict[str, Any]


@dataclass(frozen=True)
class ParsedSegment:
    sequence: int
    kind: str
    label: str | None
    start_time_utc: datetime | None
    duration_sec: float | None
    repetitions: float | None
    weight_kg: float | None
    extra_data: dict[str, Any]


@dataclass(frozen=True)
class ParsedDevice:
    message_index: int
    device_role: str
    manufacturer: str | None
    product: str | None
    display_name: str | None
    transport: str | None
    source_type: str | None
    software_version: str | None
    battery_status: str | None
    serial_number_hash: str | None
    raw_metadata: dict[str, Any]


@dataclass(frozen=True)
class ParsedMetricDefinition:
    stable_key: str
    message_name: str | None
    field_name: str | None
    unit: str | None
    value_type: str | None
    native_message_number: int | None
    developer_data_index: int | None
    field_definition_number: int | None
    application_id_hash: str | None
    device_index: int | None = None


@dataclass(frozen=True)
class ParsedFitActivity:
    status: str
    warning_count: int
    title: str
    sport: str
    sub_sport: str
    profile: str
    start_time_utc: datetime
    local_start_time: datetime | None
    utc_offset_minutes: int | None
    total_timer_time_sec: float
    total_elapsed_time_sec: float
    total_distance_m: float
    avg_hr: int | None
    max_hr: int | None
    total_calories: int | None
    avg_power_w: float | None
    max_power_w: float | None
    normalized_power_w: float | None
    total_ascent_m: float | None
    total_descent_m: float | None
    avg_speed_mps: float | None
    max_speed_mps: float | None
    avg_cadence_spm: float | None
    total_training_effect: float | None
    total_anaerobic_training_effect: float | None
    avg_temperature_c: float | None
    max_temperature_c: float | None
    min_temperature_c: float | None
    avg_gct_ms: float | None
    avg_vert_osc_mm: float | None
    avg_vertical_ratio: float | None
    avg_step_length_mm: float | None
    workout_feel: float | None
    workout_rpe: float | None
    extra_metrics: dict[str, Any]
    sessions: list[ParsedSession] = field(default_factory=list)
    records: list[ParsedRecord] = field(default_factory=list)
    laps: list[ParsedLap] = field(default_factory=list)
    segments: list[ParsedSegment] = field(default_factory=list)
    devices: list[ParsedDevice] = field(default_factory=list)
    metric_definitions: list[ParsedMetricDefinition] = field(default_factory=list)


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def _integer(value: Any) -> int | None:
    number = _number(value)
    return round(number) if number is not None else None


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
    number = _number(value)
    return FIT_EPOCH + timedelta(seconds=number) if number is not None else None


def _json_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    return str(value)


def _profile_for(sport: str, sub_sport: str) -> str:
    sport_key = sport.lower()
    sub_key = sub_sport.lower()
    if sport_key in {"hiking", "walking", "mountaineering"} or "trail" in sub_key:
        return "hike"
    if sport_key == "running":
        return "run"
    if sport_key in {"training", "strength_training", "fitness_equipment"} or "strength" in sub_key:
        return "strength"
    if sport_key in {"rock_climbing", "climbing"}:
        return "boulder" if "boulder" in sub_key else "lead"
    if sport_key == "cycling":
        return "cycling"
    return "generic"


def _cadence_spm(value: Any, sport: str, fractional: Any = None) -> float | None:
    cadence = _number(value)
    if cadence is None:
        return None
    cadence += _number(fractional) or 0
    return cadence * 2 if sport == "running" else cadence


def _developer_definitions(
    messages: dict[str, Any],
) -> tuple[dict[str, ParsedMetricDefinition], dict[int, str]]:
    application_hashes: dict[int, str] = {}
    for item in messages.get("developer_data_id_mesgs", []):
        index = _integer(item.get("developer_data_index"))
        application_id = item.get("application_id")
        if index is not None and application_id is not None:
            payload = (
                bytes(application_id)
                if isinstance(application_id, list)
                else str(application_id).encode()
            )
            application_hashes[index] = hashlib.sha256(payload).hexdigest()

    definitions: dict[str, ParsedMetricDefinition] = {}
    stable_keys: dict[int, str] = {}
    for item in messages.get("field_description_mesgs", []):
        key = _integer(item.get("key"))
        developer_index = _integer(item.get("developer_data_index"))
        field_number = _integer(item.get("field_definition_number"))
        field_name = _text(item.get("field_name"))
        if key is None:
            continue
        developer_part = developer_index if developer_index is not None else "unknown"
        field_part = field_number if field_number is not None else key
        stable_key = f"developer:{developer_part}:{field_part}:{field_name or 'unnamed'}"
        definitions[stable_key] = ParsedMetricDefinition(
            stable_key=stable_key,
            message_name=None,
            field_name=field_name,
            unit=_text(item.get("units")),
            value_type=_text(item.get("fit_base_type_id")),
            native_message_number=_integer(item.get("native_mesg_num")),
            developer_data_index=developer_index,
            field_definition_number=field_number,
            application_id_hash=application_hashes.get(
                developer_index if developer_index is not None else -1
            ),
        )
        stable_keys[key] = stable_key
    return definitions, stable_keys


def _extra_metrics(
    message_name: str,
    message: dict[Any, Any],
    known_fields: set[str],
    definitions: dict[str, ParsedMetricDefinition],
    stable_keys: dict[int, str],
) -> dict[str, Any]:
    extras: dict[str, Any] = {}
    developer_fields = message.get("developer_fields")
    if isinstance(developer_fields, dict):
        for raw_key, value in developer_fields.items():
            key = _integer(raw_key)
            stable_key = stable_keys.get(
                key if key is not None else -1, f"developer:unknown:{raw_key}"
            )
            extras[stable_key] = _json_value(value)
    for raw_key, value in message.items():
        if raw_key == "developer_fields" or (isinstance(raw_key, str) and raw_key in known_fields):
            continue
        field_name: str | None = None
        field_number: int | None = None
        if isinstance(raw_key, int):
            field_number = raw_key
        elif isinstance(raw_key, str):
            lowered = raw_key.lower()
            identity_or_free_text = {
                "serial_number",
                "ant_device_number",
                "device_number",
                "notes",
                "url",
            }
            coordinate = "position" in lowered or lowered.endswith(
                ("_lat", "_long", "_latitude", "_longitude")
            )
            if (
                lowered in identity_or_free_text
                or coordinate
                or len(raw_key) > 128
                or not raw_key.isidentifier()
            ):
                continue
            field_name = raw_key
        else:
            continue
        field_part = field_name if field_name is not None else field_number
        stable_key = f"native:{message_name}:{field_part}"
        extras[stable_key] = _json_value(value)
        definitions.setdefault(
            stable_key,
            ParsedMetricDefinition(
                stable_key=stable_key,
                message_name=message_name,
                field_name=field_name,
                unit=None,
                value_type=type(value).__name__,
                native_message_number=None,
                developer_data_index=None,
                field_definition_number=field_number,
                application_id_hash=None,
            ),
        )
    return extras


def _session_hr_zone_seconds(
    messages: dict[str, Any],
    definitions: dict[str, ParsedMetricDefinition],
) -> list[float] | None:
    """Preserve the first five FIT-stored session HR-zone durations unchanged."""
    for raw in messages.get("time_in_zone_mesgs", []):
        if _text(raw.get("reference_mesg")) != "session":
            continue
        values = raw.get("time_in_hr_zone")
        if not isinstance(values, (list, tuple)) or len(values) < 5:
            return None
        seconds = [_number(value) for value in values[:5]]
        if any(value is None or value < 0 for value in seconds):
            return None
        stable_key = "native:time_in_zone:session:time_in_hr_zone"
        definitions.setdefault(
            stable_key,
            ParsedMetricDefinition(
                stable_key=stable_key,
                message_name="time_in_zone",
                field_name="time_in_hr_zone",
                unit="s",
                value_type="list",
                native_message_number=None,
                developer_data_index=None,
                field_definition_number=None,
                application_id_hash=None,
            ),
        )
        return [value for value in seconds if value is not None]
    return None


def _devices_from_snapshots(raw_messages: list[dict[str, Any]]) -> list[ParsedDevice]:
    device_groups: dict[str, list[dict[str, Any]]] = {}
    for index, raw in enumerate(raw_messages):
        device_index = raw.get("device_index")
        explicit_identity = next(
            (
                (field, raw[field])
                for field in ("serial_number", "ant_device_number", "device_number")
                if raw.get(field) is not None
            ),
            None,
        )
        if device_index is not None:
            identity_key = f"device_index:{device_index}"
        elif explicit_identity is not None:
            field, value = explicit_identity
            identity_key = (
                f"identity_hash:{field}:" + hashlib.sha256(str(value).encode()).hexdigest()
            )
        else:
            # Same manufacturer/product metadata does not prove identity. Keep
            # anonymous snapshots separate rather than guessing they are one device.
            identity_key = f"message:{index}"
        device_groups.setdefault(identity_key, []).append(raw)

    devices: list[ParsedDevice] = []
    for index, snapshots in enumerate(device_groups.values()):
        merged_device: dict[str, Any] = {}
        for snapshot in snapshots:
            merged_device.update(
                {
                    str(key): value
                    for key, value in snapshot.items()
                    if value is not None and value != ""
                }
            )
        serial = merged_device.get("serial_number")
        serial_hash = (
            hashlib.sha256(str(serial).encode()).hexdigest() if serial is not None else None
        )
        source_type = _text(merged_device.get("source_type"))
        device_index = merged_device.get("device_index")
        device_role = (
            _text(merged_device.get("ble_device_type"))
            or _text(merged_device.get("device_type"))
            or (
                "recording_device"
                if str(device_index).lower() == "creator" or _integer(device_index) == 0
                else "device"
            )
        )
        sensitive = {"serial_number", "ant_device_number", "device_number"}
        metadata = {
            str(key): _json_value(value)
            for key, value in merged_device.items()
            if str(key) not in sensitive
        }
        metadata["snapshotCount"] = len(snapshots)
        devices.append(
            ParsedDevice(
                message_index=index,
                device_role=device_role,
                manufacturer=_text(merged_device.get("manufacturer")),
                product=_text(merged_device.get("product"))
                or _text(merged_device.get("garmin_product")),
                display_name=_text(merged_device.get("descriptor")),
                transport=source_type,
                source_type=source_type,
                software_version=_text(merged_device.get("software_version")),
                battery_status=_text(merged_device.get("battery_status"))
                or _text(merged_device.get("battery_level")),
                serial_number_hash=serial_hash,
                raw_metadata=metadata,
            )
        )
    return devices


def _semicircle_degrees(value: Any, *, latitude: bool) -> float | None:
    semicircles = _number(value)
    if semicircles is None:
        return None
    degrees = semicircles * 180 / (2**31)
    limit = 90 if latitude else 180
    return degrees if -limit <= degrees <= limit else None


SESSION_FIELDS = {
    "message_index",
    "sport",
    "sub_sport",
    "sport_profile_name",
    "start_time",
    "timestamp",
    "total_timer_time",
    "total_elapsed_time",
    "total_distance",
    "avg_heart_rate",
    "max_heart_rate",
    "total_calories",
    "avg_power",
    "max_power",
    "normalized_power",
    "total_ascent",
    "total_descent",
    "enhanced_avg_speed",
    "avg_speed",
    "enhanced_max_speed",
    "max_speed",
    "avg_cadence",
    "avg_running_cadence",
    "avg_fractional_cadence",
    "total_training_effect",
    "total_anaerobic_training_effect",
    "avg_temperature",
    "max_temperature",
    "min_temperature",
    "avg_stance_time",
    "avg_vertical_oscillation",
    "avg_vertical_ratio",
    "avg_step_length",
    "workout_feel",
    "workout_rpe",
    "developer_fields",
}
RECORD_FIELDS = {
    "timestamp",
    "distance",
    "enhanced_speed",
    "speed",
    "heart_rate",
    "power",
    "cadence",
    "fractional_cadence",
    "enhanced_altitude",
    "altitude",
    "temperature",
    "stance_time",
    "vertical_oscillation",
    "position_lat",
    "position_long",
    "developer_fields",
}
LAP_FIELDS = {
    "message_index",
    "start_time",
    "total_timer_time",
    "total_elapsed_time",
    "total_distance",
    "avg_heart_rate",
    "max_heart_rate",
    "avg_power",
    "enhanced_avg_speed",
    "avg_speed",
    "developer_fields",
}


def _safe_filename_stem(filename: str) -> str:
    stem = Path(filename).stem.strip()
    return stem[:255] if stem else "FIT 活动"


def parse_fit_file(source: Path | BinaryIO, original_filename: str) -> ParsedFitActivity:
    try:
        stream = (
            Stream.from_file(str(source))
            if isinstance(source, Path)
            else Stream.from_buffered_reader(source, os.fstat(source.fileno()).st_size)
        )
        messages, errors = Decoder(stream).read()
    except Exception as exc:
        raise FitDecodeFailure("fit_decode_failed", "FIT 文件无法解析") from exc
    if not isinstance(messages, dict):
        raise FitDecodeFailure("fit_decode_failed", "FIT 解码结果无效")

    sessions_raw = messages.get("session_mesgs", [])
    if not sessions_raw:
        raise FitDecodeFailure("fit_session_missing", "FIT 文件缺少活动会话")
    session = sessions_raw[0]
    start_time = _datetime(session.get("start_time"))
    if start_time is None:
        raise FitDecodeFailure("fit_start_time_missing", "FIT 文件缺少开始时间")

    sport = _text(session.get("sport")) or "generic"
    sub_sport = _text(session.get("sub_sport")) or "generic"
    definitions, stable_keys = _developer_definitions(messages)
    activity_message = (messages.get("activity_mesgs") or [{}])[0]
    local_start = _datetime(activity_message.get("local_timestamp"))
    local_naive = local_start.replace(tzinfo=None) if local_start is not None else None
    offset_minutes = None
    if local_naive is not None:
        offset_minutes = round((local_naive - start_time.replace(tzinfo=None)).total_seconds() / 60)
        if not -24 * 60 <= offset_minutes <= 24 * 60:
            local_naive = None
            offset_minutes = None

    sessions: list[ParsedSession] = []
    for index, raw in enumerate(sessions_raw):
        summary = {
            str(key): _json_value(value)
            for key, value in raw.items()
            if key != "developer_fields"
            and "position_lat" not in str(key)
            and "position_long" not in str(key)
            and str(key) not in {"nec_lat", "nec_long", "swc_lat", "swc_long", "serial_number"}
        }
        summary["extra_metrics"] = _extra_metrics(
            "session", raw, SESSION_FIELDS, definitions, stable_keys
        )
        sessions.append(
            ParsedSession(
                message_index=_integer(raw.get("message_index")) or index,
                sport=_text(raw.get("sport")) or sport,
                sub_sport=_text(raw.get("sub_sport")) or sub_sport,
                start_time_utc=_datetime(raw.get("start_time")),
                summary=summary,
            )
        )

    records: list[ParsedRecord] = []
    for index, raw in enumerate(messages.get("record_mesgs", [])):
        timestamp = _datetime(raw.get("timestamp"))
        elapsed = (
            (timestamp - start_time).total_seconds() if timestamp is not None else float(index)
        )
        records.append(
            ParsedRecord(
                sequence=index,
                timestamp=timestamp,
                elapsed_sec=max(0.0, elapsed),
                distance_m=_number(raw.get("distance")),
                speed_mps=_number(raw.get("enhanced_speed")) or _number(raw.get("speed")),
                heart_rate=_integer(raw.get("heart_rate")),
                power_w=_number(raw.get("power")),
                cadence_spm=_cadence_spm(raw.get("cadence"), sport, raw.get("fractional_cadence")),
                altitude_m=_number(raw.get("enhanced_altitude")) or _number(raw.get("altitude")),
                temperature_c=_number(raw.get("temperature")),
                stance_time_ms=_number(raw.get("stance_time")),
                vertical_oscillation_mm=_number(raw.get("vertical_oscillation")),
                position_lat=_semicircle_degrees(raw.get("position_lat"), latitude=True),
                position_long=_semicircle_degrees(raw.get("position_long"), latitude=False),
                extra_metrics=_extra_metrics(
                    "record", raw, RECORD_FIELDS, definitions, stable_keys
                ),
            )
        )

    laps: list[ParsedLap] = []
    for index, raw in enumerate(messages.get("lap_mesgs", [])):
        laps.append(
            ParsedLap(
                message_index=_integer(raw.get("message_index")) or index,
                start_time_utc=_datetime(raw.get("start_time")),
                duration_sec=_number(raw.get("total_timer_time"))
                or _number(raw.get("total_elapsed_time"))
                or 0,
                distance_m=_number(raw.get("total_distance")) or 0,
                avg_hr=_integer(raw.get("avg_heart_rate")),
                max_hr=_integer(raw.get("max_heart_rate")),
                avg_power_w=_number(raw.get("avg_power")),
                avg_speed_mps=_number(raw.get("enhanced_avg_speed"))
                or _number(raw.get("avg_speed")),
                extra_metrics=_extra_metrics("lap", raw, LAP_FIELDS, definitions, stable_keys),
            )
        )

    title_by_index = {
        _integer(item.get("message_index")): _text(item.get("exercise_name"))
        or _text(item.get("wkt_step_name"))
        for item in messages.get("exercise_title_mesgs", [])
    }
    segments: list[ParsedSegment] = []
    segment_sources = (
        ("set", messages.get("set_mesgs", [])),
        ("split", messages.get("split_mesgs", [])),
        ("split_summary", messages.get("split_summary_mesgs", [])),
    )
    for source_name, source_messages in segment_sources:
        for raw in source_messages:
            message_index = _integer(raw.get("message_index"))
            kind = _text(raw.get("set_type")) or _text(raw.get("split_type")) or source_name
            weight = _number(raw.get("weight"))
            if weight is not None and weight > 1000:
                weight /= 1000
            label = (
                title_by_index.get(message_index)
                or _text(raw.get("exercise_category"))
                or _text(raw.get("category"))
                or _text(raw.get("name"))
            )
            excluded = {"serial_number", "notes", "url", "position_lat", "position_long"}
            extra = {
                str(key): _json_value(value)
                for key, value in raw.items()
                if str(key) not in excluded
            }
            # set, split and split_summary are distinct FIT message families.
            # Persist all of them for lossless replay, but make the provenance
            # explicit so consumers never count a summary as an instance.
            extra["sourceMessage"] = source_name
            segments.append(
                ParsedSegment(
                    sequence=len(segments),
                    kind=kind,
                    label=label,
                    start_time_utc=_datetime(raw.get("start_time")),
                    duration_sec=_number(raw.get("total_timer_time"))
                    or _number(raw.get("duration")),
                    repetitions=_number(raw.get("repetitions")),
                    weight_kg=weight,
                    extra_data=extra,
                )
            )

    devices = _devices_from_snapshots(messages.get("device_info_mesgs", []))

    extra_metrics = _extra_metrics("session", session, SESSION_FIELDS, definitions, stable_keys)
    hr_zone_seconds = _session_hr_zone_seconds(messages, definitions)
    if hr_zone_seconds is not None:
        zone_key = "native:time_in_zone:session:time_in_hr_zone"
        extra_metrics[zone_key] = hr_zone_seconds
        if sessions:
            session_extras = sessions[0].summary.get("extra_metrics")
            if isinstance(session_extras, dict):
                session_extras[zone_key] = hr_zone_seconds
    return ParsedFitActivity(
        status="partial" if errors else "complete",
        warning_count=len(errors),
        title=_text(session.get("sport_profile_name")) or _safe_filename_stem(original_filename),
        sport=sport,
        sub_sport=sub_sport,
        profile=_profile_for(sport, sub_sport),
        start_time_utc=start_time,
        local_start_time=local_naive,
        utc_offset_minutes=offset_minutes,
        total_timer_time_sec=_number(session.get("total_timer_time")) or 0,
        total_elapsed_time_sec=_number(session.get("total_elapsed_time")) or 0,
        total_distance_m=_number(session.get("total_distance")) or 0,
        avg_hr=_integer(session.get("avg_heart_rate")),
        max_hr=_integer(session.get("max_heart_rate")),
        total_calories=_integer(session.get("total_calories")),
        avg_power_w=_number(session.get("avg_power")),
        max_power_w=_number(session.get("max_power")),
        normalized_power_w=_number(session.get("normalized_power")),
        total_ascent_m=_number(session.get("total_ascent")),
        total_descent_m=_number(session.get("total_descent")),
        avg_speed_mps=_number(session.get("enhanced_avg_speed"))
        or _number(session.get("avg_speed")),
        max_speed_mps=_number(session.get("enhanced_max_speed"))
        or _number(session.get("max_speed")),
        avg_cadence_spm=_cadence_spm(
            session.get("avg_cadence", session.get("avg_running_cadence")),
            sport,
            session.get("avg_fractional_cadence"),
        ),
        total_training_effect=_number(session.get("total_training_effect")),
        total_anaerobic_training_effect=_number(session.get("total_anaerobic_training_effect")),
        avg_temperature_c=_number(session.get("avg_temperature")),
        max_temperature_c=_number(session.get("max_temperature")),
        min_temperature_c=_number(session.get("min_temperature")),
        avg_gct_ms=_number(session.get("avg_stance_time")),
        avg_vert_osc_mm=_number(session.get("avg_vertical_oscillation")),
        avg_vertical_ratio=_number(session.get("avg_vertical_ratio")),
        avg_step_length_mm=_number(session.get("avg_step_length")),
        workout_feel=_number(session.get("workout_feel")),
        workout_rpe=_number(session.get("workout_rpe")),
        extra_metrics=extra_metrics,
        sessions=sessions,
        records=records,
        laps=laps,
        segments=segments,
        devices=devices,
        metric_definitions=sorted(definitions.values(), key=lambda item: item.stable_key),
    )
