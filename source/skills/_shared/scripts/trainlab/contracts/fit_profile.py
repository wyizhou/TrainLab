from __future__ import annotations

from typing import Any

from garmin_fit_sdk.profile import Profile

TIME_TYPES = frozenset({"date_time", "local_date_time"})


def profile(number: int) -> dict[str, Any]:
    return dict(Profile["messages"].get(number, {"name": None, "fields": {}}))


def unit_of(field: dict[str, Any]) -> str | None:
    unit = field.get("units")
    if isinstance(unit, list):
        unit = ",".join(unit)
    return unit or None


def value_form(field: dict[str, Any]) -> str:
    return (
        "physical"
        if field and field.get("type") not in TIME_TYPES and len(field.get("scale", [1])) == 1
        else "raw"
    )


def validate_message_identity(number: int, name: str | None) -> None:
    if profile(number)["name"] != name:
        raise ValueError("message name/number mismatch")


def field_profile(definition: dict[str, Any]) -> dict[str, Any]:
    field = profile(definition["message_number"])["fields"].get(definition["field_number"], {})
    if definition["origin"] == "expanded":
        for sub in field.get("sub_fields", []):
            if sub["name"] == definition["name"]:
                return dict(sub)
    return dict(field)


def validate_definition_identity(definition: dict[str, Any], definitions: dict[str, Any]) -> None:
    validate_message_identity(definition["message_number"], definition["message_name"])
    if definition["source_ref"] is not None:
        return
    field = field_profile(definition)
    if (
        definition["name"] != field.get("name")
        or definition["unit"] != unit_of(field)
        or definition["value_form"] != value_form(field)
    ):
        raise ValueError("field Profile identity mismatch")
    if field.get("type") in TIME_TYPES and definition["base_type"] != field["base_type"]:
        raise ValueError("invalid time base type")
    if definition["origin"] == "expanded":
        parent = definitions[definition["component_of"]]
        parent_profile = field_profile(parent)
        subfield = definition["field_number"] == parent[
            "field_number"
        ] and field in parent_profile.get("sub_fields", [])
        component = definition["field_number"] in parent_profile.get("components", [])
        if not (subfield or component):
            raise ValueError("expanded field not defined by Profile parent")
