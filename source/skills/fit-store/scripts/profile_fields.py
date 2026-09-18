from __future__ import annotations

from typing import Any

from garmin_fit_sdk.fit import BASE_TYPE_DEFINITIONS, FIELD_TYPE_TO_BASE_TYPE
from garmin_fit_sdk.profile import Profile

from trainlab.contracts.fit_profile import TIME_TYPES, profile, unit_of, value_form
from trainlab.fit.wire import WireMessage, base_name, raw_value

PRIVATE_MESSAGES = frozenset(
    {
        "user_profile",
        "weight_scale",
        "blood_pressure",
        "monitoring",
        "monitoring_info",
        "ant_rx",
        "ant_tx",
    }
)
PRIVATE_NAMES = frozenset(
    {
        "serial_number",
        "ant_device_number",
        "device_number",
        "device_id",
        "developer_id",
        "application_id",
        "friendly_name",
        "user_name",
        "user_id",
        "user_profile_index",
    }
)


def packed_json(value: Any) -> Any:
    if isinstance(value, list):
        return [packed_json(v) for v in value]
    if type(value) in (int, float) and abs(value) > 9007199254740991:
        return {"integer": str(int(value))}
    return value


def physical(raw: Any, field: dict[str, Any]) -> Any:
    if isinstance(raw, list):
        return [physical(v, field) for v in raw]
    if raw is None or field.get("type") in TIME_TYPES:
        return raw
    enum = Profile["types"].get(field.get("type"), {})
    if enum:
        return enum.get(raw, raw)
    scales = field.get("scale", [1])
    offsets = field.get("offset", [0])
    if isinstance(raw, (int, float)) and len(scales) == 1:
        scale = scales[0]
        offset = offsets[0] if offsets else 0
        if scale == 0:
            raise ValueError("invalid scale")
        return (raw if scale == 1 else raw / scale) - offset
    return raw


class FieldMapper:
    def __init__(self) -> None:
        self.definitions: dict[str, Any] = {}
        self.sources: dict[str, Any] = {}
        self.identities: dict[tuple[Any, ...], str] = {}
        self.source_indexes: dict[tuple[int, int], str] = {}
        self.descriptions: dict[tuple[int, int, int], tuple[int, dict[int, Any]]] = {}
        self.accumulated: dict[tuple[Any, ...], int] = {}

    def source(self, chain: int, index: int, manufacturer: Any = None, new: bool = False) -> str:
        key = (chain, index)
        if new or key not in self.source_indexes:
            alias = "d" + str(len(self.sources))
            self.sources[alias] = {
                "chain_index": chain,
                "developer_data_index": index,
                "application_name": None,
                "manufacturer": manufacturer,
            }
            self.source_indexes[key] = alias
            if new:
                self.descriptions = {k: v for k, v in self.descriptions.items() if k[:2] != key}
        return self.source_indexes[key]

    def fields(self, message: WireMessage) -> dict[str, Any]:
        p = profile(message.number)
        raw = {f.number: f.raw for f in message.fields}
        if message.number == 207 and type(raw.get(3)) is int:
            self.source(message.chain, raw[3], raw.get(2), new=True)
        if message.number == 206:
            if (
                type(raw.get(0)) is not int
                or type(raw.get(1)) is not int
                or type(raw.get(2)) is not int
            ):
                raise ValueError("incomplete developer field description")
            if (message.chain, raw[0]) not in self.source_indexes:
                raise ValueError("developer description lacks source")
            self.descriptions[(message.chain, raw[0], raw[1])] = (message.index, raw)
        result: dict[str, Any] = {"standard": {}, "developer": {}}
        if p["name"] not in PRIVATE_MESSAGES:
            for field in message.fields:
                if p["fields"].get(field.number, {}).get("is_accumulated"):
                    values = field.raw if isinstance(field.raw, list) else [field.raw]
                    for raw_item in values:
                        if type(raw_item) is int:
                            self.accumulated[(message.chain, message.number, field.number)] = (
                                raw_item
                            )
            for field in message.fields:
                fp = p["fields"].get(field.number, {})
                if fp.get("name") in PRIVATE_NAMES:
                    continue
                value = physical(field.raw, fp)
                if field.base_type == 13 and not fp:
                    value = (
                        None
                        if all(v == 255 for v in field.encoded)
                        else {"bytes_hex": field.encoded.hex()}
                    )
                key = self.add(
                    message, field.number, base_name(field.base_type), fp, None, "direct", None, 0
                )
                result["standard"][key] = packed_json(value)
                if field.raw is not None:
                    self.expand(message, field.number, field.raw, fp, key, result["standard"], ())
                    for sub in fp.get("sub_fields", []):
                        if any(raw.get(m["num"]) == m["raw_value"] for m in sub["map"]):
                            subkey = self.add(
                                message,
                                field.number,
                                base_name(field.base_type),
                                sub,
                                None,
                                "expanded",
                                key,
                                0,
                            )
                            result["standard"][subkey] = packed_json(physical(field.raw, sub))
                            self.expand(
                                message,
                                field.number,
                                field.raw,
                                sub,
                                subkey,
                                result["standard"],
                                (),
                            )
        for index, number, encoded in message.developers:
            if (message.chain, index) not in self.source_indexes or (
                message.chain,
                index,
                number,
            ) not in self.descriptions:
                raise ValueError("developer field lacks source/description")
            source = self.source_indexes[(message.chain, index)]
            revision, meta = self.descriptions[(message.chain, index, number)]
            type_id = meta.get(2, 13) & 31
            if type_id not in BASE_TYPE_DEFINITIONS:
                raise ValueError("invalid developer base type")
            raw_dev = raw_value(encoded, type_id, message.endian)
            fp = {
                "name": meta.get(3),
                "units": meta.get(8),
                "type": base_name(type_id),
                "scale": [meta.get(6) or 1],
                "offset": [meta.get(7) or 0],
            }
            if fp["name"] in PRIVATE_NAMES:
                continue
            value = (
                physical(raw_dev, fp)
                if meta
                else (None if all(v == 255 for v in encoded) else {"bytes_hex": encoded.hex()})
            )
            key = self.add(
                message,
                number,
                base_name(type_id),
                fp if meta else {},
                source,
                "direct",
                None,
                revision,
            )
            result["developer"][key] = packed_json(value)
        return result

    def add(
        self,
        m: WireMessage,
        number: int,
        base: str,
        fp: dict[str, Any],
        source: str | None,
        origin: str,
        parent: str | None,
        revision: int,
    ) -> str:
        identity = (m.chain, m.definition, number, source, revision, origin, parent, fp.get("name"))
        if identity not in self.identities:
            key = "f" + str(len(self.definitions))
            self.identities[identity] = key
            self.definitions[key] = {
                "message_number": m.number,
                "message_name": profile(m.number)["name"],
                "field_number": number,
                "name": fp.get("name"),
                "base_type": base,
                "unit": unit_of(fp),
                "origin": origin,
                "source_ref": source,
                "definition_index": m.definition,
                "chain_index": m.chain,
                "component_of": parent,
                "value_form": value_form(fp),
            }
        return self.identities[identity]

    def expand(
        self,
        m: WireMessage,
        number: int,
        raw: Any,
        fp: dict[str, Any],
        parent: str,
        result: dict[str, Any],
        trail: tuple[int, ...],
    ) -> None:
        if not fp.get("has_components"):
            return
        if number in trail:
            raise ValueError("cyclic Profile component")
        base = FIELD_TYPE_TO_BASE_TYPE.get(str(fp.get("type", "")))
        if base is None:
            return
        size = BASE_TYPE_DEFINITIONS[base]["size"] * 8
        values = raw if isinstance(raw, list) else [raw]
        if any(v is None for v in values):
            return
        bits = sum((int(v) & ((1 << size) - 1)) << (size * i) for i, v in enumerate(values))
        available = size * len(values)
        consumed = 0
        for i, target in enumerate(fp["components"]):
            width = fp["bits"][i]
            if consumed + width > available:
                break
            value = (bits >> consumed) & ((1 << width) - 1)
            consumed += width
            target_profile = profile(m.number)["fields"][target]
            scale = fp["scale"][i]
            if target_profile.get("is_accumulated"):
                k = (m.chain, m.number, target)
                previous_raw = self.accumulated.get(k, 0)
                previous_physical = (
                    previous_raw / target_profile["scale"][0] - target_profile["offset"][0]
                )
                previous = round((previous_physical + fp["offset"][i]) * scale)
                value = previous + ((value - previous) & ((1 << width) - 1))
            physical_value = (value if scale == 1 else value / scale) - fp["offset"][i]
            raw_target = (physical_value + target_profile["offset"][0]) * target_profile["scale"][0]
            raw_target = int(raw_target) if raw_target == int(raw_target) else raw_target
            if target_profile.get("is_accumulated"):
                self.accumulated[(m.chain, m.number, target)] = round(raw_target)
            key = self.add(
                m, target, target_profile["base_type"], target_profile, None, "expanded", parent, 0
            )
            invalid = BASE_TYPE_DEFINITIONS[FIELD_TYPE_TO_BASE_TYPE[target_profile["base_type"]]][
                "invalid"
            ]
            output = None if raw_target == invalid else physical_value
            if key in result:
                existing = result[key]
                result[key] = (
                    existing + [output] if isinstance(existing, list) else [existing, output]
                )
            else:
                result[key] = packed_json(output)
            if output is not None:
                self.expand(m, target, raw_target, target_profile, key, result, (*trail, number))
