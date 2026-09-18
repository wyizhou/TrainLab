from __future__ import annotations

import json
import math
from functools import lru_cache
from importlib.resources import files
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import ValidationError

from trainlab.contracts.fit_consistency import validate_record_time
from trainlab.contracts.fit_profile import validate_definition_identity, validate_message_identity


def strict_json(value: Any) -> None:
    if value is None or type(value) in (bool, str):
        if isinstance(value, str):
            value.encode("utf-8", errors="strict")
        return
    if type(value) is int:
        if abs(value) > 9007199254740991:
            raise ValueError("large integer must use integer wrapper")
        return
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError("non-finite number")
        return
    if type(value) is list:
        for item in value:
            strict_json(item)
        return
    if type(value) is dict and all(type(key) is str for key in value):
        for key, item in value.items():
            strict_json(key)
            strict_json(item)
        return
    raise ValueError("not a strict JSON value")


def loads(text: str) -> Any:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    result = json.loads(text, object_pairs_hook=pairs)
    strict_json(result)
    return result


@lru_cache
def schema_document() -> dict[str, Any]:
    return dict(
        loads(
            files("trainlab_schemas").joinpath("contracts.schema.json").read_text(encoding="utf-8")
        )
    )


def schema_for(name: str) -> dict[str, Any]:
    document = schema_document()
    return {"$schema": document["$schema"], "$defs": document["$defs"], "$ref": f"#/$defs/{name}"}


@lru_cache
def validator(name: str) -> Draft202012Validator:
    schema = schema_for(name)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def validate(name: str, payload: dict[str, Any]) -> None:
    strict_json(payload)
    try:
        validator(name).validate(payload)
    except ValidationError as exc:
        raise ValueError(
            "invalid " + name + " at " + "/".join(map(str, exc.absolute_path))
        ) from exc
    if name == "ParsedActivity":
        for key in ("sport", "sub_sport", "start_time_utc", "end_time_utc"):
            if payload[key] != payload["basic_json"][key]:
                raise ValueError("SQL/basic mismatch: " + key)
        validate_references(payload, payload["sensors_json"], payload["records"])
    elif name == "ActivityFacts":
        validate_references(payload, payload, [])
    elif name == "GetRunningRecordsResult" and payload["ok"]:
        validate_references({}, payload["data"], payload["data"]["records"])


def definition_closure(ids: set[str], definitions: dict[str, Any]) -> set[str]:
    todo = list(ids)
    while todo:
        key = todo.pop()
        if key not in definitions:
            raise ValueError("undefined field reference")
        parent = definitions[key]["component_of"]
        if parent is not None and parent not in ids:
            ids.add(parent)
            todo.append(parent)
    return ids


def validate_references(
    payload: dict[str, Any], dictionary: dict[str, Any], records: list[Any]
) -> None:
    definitions = dictionary["field_definitions"]
    sources = dictionary["developer_sources"]
    identities_by_definition: dict[int, tuple[int, int]] = {}
    for key, definition in definitions.items():
        identity = (definition["chain_index"], definition["message_number"])
        index = definition["definition_index"]
        if identities_by_definition.setdefault(index, identity) != identity:
            raise ValueError("definition reused across message identities")
        source = definition["source_ref"]
        if source is not None and (
            source not in sources or sources[source]["chain_index"] != definition["chain_index"]
        ):
            raise ValueError("invalid developer source")
        parent = definition["component_of"]
        if (definition["origin"] == "expanded") != (parent is not None):
            raise ValueError("invalid component origin")
        seen = {key}
        while parent is not None:
            if parent not in definitions or parent in seen:
                raise ValueError("invalid component reference")
            seen.add(parent)
            other = definitions[parent]
            if any(
                other[k] != definition[k]
                for k in ("message_number", "chain_index", "definition_index", "source_ref")
            ):
                raise ValueError("component identity mismatch")
            parent = other["component_of"]
        validate_definition_identity(definition, definitions)

    def fields(fieldset: dict[str, Any], number: int, chain: int | None) -> None:
        identities = set()
        field_identities = set()
        for category in ("standard", "developer"):
            for key in fieldset[category]:
                if key not in definitions:
                    raise ValueError("undefined field")
                definition = definitions[key]
                if (definition["source_ref"] is not None) != (category == "developer"):
                    raise ValueError("field source category mismatch")
                if definition["message_number"] != number or (
                    chain is not None and definition["chain_index"] != chain
                ):
                    raise ValueError("field message identity mismatch")
                field_identity = (
                    category,
                    definition["field_number"],
                    definition["source_ref"],
                    definition["origin"],
                    definition["component_of"],
                    definition["name"],
                )
                if field_identity in field_identities:
                    raise ValueError("duplicate field identity")
                field_identities.add(field_identity)
                identities.add((definition["chain_index"], definition["definition_index"]))
        if len(identities) > 1:
            raise ValueError("fieldset mixes message definitions")

    indexes: set[int] = set()
    for container, key in [
        ("basic_json", "messages"),
        ("summary_json", "messages"),
        ("segments_json", "items"),
        ("sensors_json", "messages"),
    ]:
        previous = -1
        for message in payload.get(container, {}).get(key, []):
            index = message["message_index"]
            if index in indexes or index <= previous:
                raise ValueError("message order/index mismatch")
            indexes.add(index)
            previous = index
            validate_message_identity(message["message_number"], message["message_name"])
            fields(message["fields"], message["message_number"], message["chain_index"])
    for index, record in enumerate(records):
        if record["record_index"] != index:
            raise ValueError("non-contiguous record index")
        fields(record["metrics_json"], 20, None)
        validate_record_time(record, definitions)
