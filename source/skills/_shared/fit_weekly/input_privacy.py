"""One read-only admission policy for model-bound goal and history content.

Closed, provenance-checked structures are selected by weekly_context. This
module detects declared private categories within those structures; it neither
redacts immutable records nor promises detection of unlabeled secrets.
"""

from __future__ import annotations

import json
import re
import unicodedata
from typing import Any

# All categories share label syntax, including camelCase and nested JSON keys.
# A route label alone is NOT private: its value must have geographical shape.
CATEGORIES = {
    "host_path": (
        "file_path",
        "host_path",
        "source_path",
        "fit_path",
        "source_file",
        "文件路径",
        "主机路径",
        "原始文件路径",
    ),
    "raw": (
        "raw_fit",
        "fit_bytes",
        "raw_fit_bytes",
        "fit_base64",
        "original_fit",
        "raw_payload",
        "raw_data",
        "raw_response",
        "原始FIT",
        "原始载荷",
    ),
    "geography": (
        "gps",
        "latitude",
        "longitude",
        "lat",
        "lon",
        "lng",
        "position_lat",
        "position_long",
        "coordinates",
        "coordinate",
        "geo_coordinates",
        "route_coordinates",
        "track_coordinates",
        "经纬度",
        "纬度",
        "经度",
        "坐标",
        "路线坐标",
        "轨迹坐标",
        "route_points",
        "track_points",
        "路线点列",
        "轨迹点列",
        "encoded_polyline",
    ),
    "identity": (
        "activity_name",
        "activity_title",
        "活动名称",
        "活动名",
        "device_id",
        "device_number",
        "device_serial",
        "device_serial_number",
        "serial_number",
        "full_name",
        "email",
        "email_address",
        "邮箱",
        "电子邮件地址",
        *(
            f"{owner}_{kind}"
            for owner in ("athlete", "user", "account", "person")
            for kind in ("id", "name")
        ),
        *(
            f"{owner}{kind}"
            for owner in ("设备", "用户", "账号", "个人")
            for kind in ("ID", "编号", "标识", "序列号", "姓名")
        ),
    ),
    "authentication": (
        "token",
        "access_token",
        "refresh_token",
        "id_token",
        "api_token",
        "api_key",
        "password",
        "credential",
        "credentials",
        "client_secret",
        "authorization",
        "authentication",
        "auth_info",
        "auth_header",
        "authentication_header",
        "authorization_header",
        "cookie",
        "session_token",
        "密码",
        "令牌",
        "凭据",
        "认证信息",
        "认证头",
        "认证请求头",
        "授权头",
        "授权请求头",
    ),
}
ROUTE_LABELS = ("route", "track", "trajectory", "polyline", "路线", "轨迹", "路径")
ROUTE_POINTS = ("points", "point", "vertices", "waypoints", "点", "点列", "途经点")


def labels(values: tuple[str, ...]) -> str:
    return (
        "(?:"
        + "|".join(
            re.escape(v).replace("_", "[_ -]?")
            for v in sorted(values, key=len, reverse=True)
        )
        + ")"
    )


FLAGS = re.IGNORECASE | re.ASCII
PRIVATE_LABEL = re.compile(
    labels(tuple(v for group in CATEGORIES.values() for v in group)), FLAGS
)
ROUTE_LABEL = re.compile(labels(ROUTE_LABELS), FLAGS)
POINT_LABEL = re.compile(labels(ROUTE_POINTS), FLAGS)
SEPARATOR = r"\s*[\"'”’]?\s*[:：=]\s*"
PRIVATE_ASSIGNMENT = re.compile(
    r"(?<![a-z0-9_])" + PRIVATE_LABEL.pattern + SEPARATOR + r"\S", FLAGS
)
ROUTE_ASSIGNMENT = re.compile(
    r"(?<![a-z0-9_])" + ROUTE_LABEL.pattern + SEPARATOR, FLAGS
)
POINT_ASSIGNMENT = re.compile(
    r"(?<![a-z0-9_])" + POINT_LABEL.pattern + SEPARATOR + r"\S", FLAGS
)
PRIVATE_TEXT = re.compile(
    r"[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Z0-9.-]+\.[A-Z]{2,}"
    r"|\bbearer\s+\S|\bGPS\b|\bfile:[\\/]"
    r"|(?:^|[\s\"'=:：(（])(?:/(?:[^\s/]|$)|[A-Z]:[\\/]|\\\\|\.\.?[/\\]|~[/\\])"
    r"|(?:[a-z0-9_.-]+[/\\])+[a-z0-9_.-]+\.(?:fit|json|sqlite|db|md|py|txt)\b",
    FLAGS,
)
SPORTS_LABELS = {"activity_name", "activity_title", "活动名称", "活动名"}
PROTECTED_LABEL = re.compile(
    labels(
        tuple(
            v
            for category, group in CATEGORIES.items()
            if category != "geography"
            for v in group
            if v not in SPORTS_LABELS
        )
    ),
    FLAGS,
)
PROTECTED_ASSIGNMENT = re.compile(
    r"(?<![a-z0-9_])" + PROTECTED_LABEL.pattern + SEPARATOR + r"\S", FLAGS
)
PROTECTED_TEXT = re.compile(PRIVATE_TEXT.pattern.replace(r"|\bGPS\b", ""), FLAGS)
NUMBER = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?"
NUMERIC = re.compile(r"(?:" + NUMBER + r"|[+-]?(?:nan|inf(?:inity)?))\Z", FLAGS)
PAIR = re.compile(
    r"(?<![\w.])(?P<first>"
    + NUMBER
    + r")\s*(?:[,，;；|]|\s)\s*(?P<second>"
    + NUMBER
    + r")(?![\w.])",
    FLAGS,
)
SCALAR = (
    r"""(?:"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|“[^”]*”|‘[^’]*’|"""
    r"[^\s,，;；|()\[\]{}]+)"
)
SCALAR_PAIR = re.compile(
    r"(?<![^\s,，;；|()\[\]{}])(?P<first>"
    + SCALAR
    + r")\s*[,，;；|]\s*(?P<second>"
    + SCALAR
    + r")",
    FLAGS,
)
SPORT_UNIT = re.compile(
    r"(?:km|m|cm|mm|mi|mile[s]?|kilomet(?:er|re)[s]?|met(?:er|re)[s]?|"
    r"h|hr|hour[s]?|min|minute[s]?|s|sec|second[s]?|bpm|w|watt[s]?|rpm|spm|"
    r"rpe|rep[s]?|repeat[s]?|repetition[s]?|公里|千米|米|分钟|小时|秒|次|组|瓦)(?![a-z])",
    FLAGS,
)
GEO_TYPES = (
    "Point",
    "MultiPoint",
    "LineString",
    "MultiLineString",
    "Polygon",
    "MultiPolygon",
    "GeometryCollection",
)
GEO_TYPE = re.compile(
    r"(?<![a-z0-9_])type"
    + SEPARATOR
    + r"[\"'‘“]?"
    + labels(GEO_TYPES)
    + r"(?![a-z0-9_])",
    FLAGS,
)
DEGREE_PAIR = re.compile(
    NUMBER + r"\s*°\s*[NS]?\s*(?:[,，;；|]|\s)\s*" + NUMBER + r"\s*°\s*[EW]?", FLAGS
)
ANGLE = (
    NUMBER
    + r"\s*(?:°\s*(?:"
    + NUMBER
    + r"\s*['′]\s*(?:"
    + NUMBER
    + r"""\s*["″]\s*)?)?)?"""
)
HEMISPHERE_PAIR = re.compile(
    ANGLE + r"[NS]\s*(?:[,，;；|]|\s)\s*" + ANGLE + r"[EW](?![a-z])", FLAGS
)


def scan_views(text: str) -> tuple[str, str]:
    # Only detector views are normalized; no value is written back to the caller.
    return text, unicodedata.normalize("NFKC", text)


def label_matches(pattern: re.Pattern[str], text: str) -> bool:
    return any(pattern.fullmatch(view.strip()) for view in scan_views(text))


def number_like(value: Any) -> bool:
    return type(value) in (int, float) or (
        isinstance(value, str) and bool(NUMERIC.fullmatch(value.strip()))
    )


def point_pair(text: str) -> bool:
    # Parse complete scalar fragments, not the whole prose prefix or a lone
    # number in brackets. Units remain attached to sports facts, never stripped.
    def unit_after(end: int) -> bool:
        return bool(SPORT_UNIT.match(text[end:].lstrip()))

    for match in PAIR.finditer(text):
        if not unit_after(match.end()):
            return True
    for match in SCALAR_PAIR.finditer(text):
        first, second = (match[name].strip("\"'‘’“”") for name in ("first", "second"))
        if not (number_like(first) or number_like(second)):
            continue
        if SPORT_UNIT.fullmatch(first) or SPORT_UNIT.fullmatch(second):
            continue
        if number_like(second):
            if not unit_after(match.end()):
                return True
        elif number_like(first):
            # A damaged second scalar must still occupy a complete slot, not
            # be the first word of another ordinary unit-bearing description.
            suffix = re.split(r"[,，;；|()\[\]{}\n]", text[match.end() :], maxsplit=1)[
                0
            ]
            if not suffix.strip():
                return True
    return False


def route_coordinates(value: Any) -> bool:
    """Apply shape checks ONLY after a route/track label supplies geo meaning.

    Do not range-check coordinates here: invalid or partly broken coordinates
    are still forbidden input, not permission to transmit the remaining points.
    """
    if isinstance(value, dict):
        sports_fields = {"training", "segments", "laps", "work", "recovery"}
        return any(
            label_matches(PRIVATE_LABEL, k)
            or (label_matches(POINT_LABEL, k) and isinstance(v, (list, dict)))
            or (k not in sports_fields and route_coordinates(v))
            for k, v in value.items()
        )
    if isinstance(value, list):
        if len(value) >= 2 and any(number_like(v) for v in value):
            return True
        return any(route_coordinates(v) for v in value)
    if isinstance(value, str):
        for view in scan_views(value):
            text = view.lstrip(" \t\r\n\"'‘’“”`")
            if text.startswith(("{", "[")):
                try:
                    decoded, end = json.JSONDecoder().raw_decode(text)
                except ValueError:
                    pass
                else:
                    # Valid route metadata is interpreted structurally, so a
                    # distance or RPE inside JSON is not guessed to be a point.
                    if route_coordinates(decoded):
                        return True
                    # A valid metadata prefix does not admit the trailing text.
                    text = text[end:].lstrip()
            if PRIVATE_ASSIGNMENT.search(text):
                return True
            for match in POINT_ASSIGNMENT.finditer(text):
                if route_coordinates(text[match.end() :]):
                    return True
            # Bare prose, tuples and damaged containers use the same two-slot
            # rule; brackets alone do not supply coordinate shape.
            if (
                point_pair(text)
                or DEGREE_PAIR.search(text)
                or HEMISPHERE_PAIR.search(text)
            ):
                return True
    return False


def check(value: Any, *, allow_sports_location: bool = False) -> None:
    private_label = PROTECTED_LABEL if allow_sports_location else PRIVATE_LABEL
    private_assignment = (
        PROTECTED_ASSIGNMENT if allow_sports_location else PRIVATE_ASSIGNMENT
    )
    private_text = PROTECTED_TEXT if allow_sports_location else PRIVATE_TEXT
    if isinstance(value, dict):
        if not allow_sports_location and any(
            isinstance(k, str)
            and any(v.strip().lower() == "type" for v in scan_views(k))
            and isinstance(item, str)
            and any(
                v.lower() in {t.lower() for t in GEO_TYPES} for v in scan_views(item)
            )
            for k, item in value.items()
        ):
            raise ValueError("weekly_private_text")
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("weekly_private_text")
            if label_matches(private_label, key) or (
                not allow_sports_location
                and label_matches(ROUTE_LABEL, key)
                and route_coordinates(item)
            ):
                raise ValueError("weekly_private_text")
            check(key, allow_sports_location=allow_sports_location)
            check(item, allow_sports_location=allow_sports_location)
    elif isinstance(value, list):
        for item in value:
            check(item, allow_sports_location=allow_sports_location)
    elif isinstance(value, str):
        for view in scan_views(value):
            if (
                private_text.search(view)
                or private_assignment.search(view)
                or (not allow_sports_location and GEO_TYPE.search(view))
            ):
                raise ValueError("weekly_private_text")
            for match in (
                () if allow_sports_location else ROUTE_ASSIGNMENT.finditer(view)
            ):
                if route_coordinates(view[match.end() :]):
                    raise ValueError("weekly_private_text")
