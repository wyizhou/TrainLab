"""Validated, schedule-free configuration for the one-shot Garmin tool."""
from __future__ import annotations

import json
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

from .foundation import FoundationConfig
from .garmin import GarminConfig


def load_garmin_config(project_root: Path, foundation: FoundationConfig | None = None) -> GarminConfig:
    foundation = foundation or FoundationConfig.load(project_root)
    payload = yaml.safe_load((project_root / "config" / "garmin.yaml").read_text(encoding="utf-8"))
    schema = json.loads((project_root / "harness" / "schemas" / "garmin_config.schema.json").read_text(encoding="utf-8"))
    if list(Draft202012Validator(schema).iter_errors(payload)):
        raise ValueError("invalid_garmin_configuration")
    values = payload["garmin"]
    token = (project_root / values["token_store"]).resolve()
    if foundation.state_root not in token.parents:
        raise ValueError("garmin_token_store_outside_state")
    return GarminConfig(
        database_path=foundation.database_path, raw_root=foundation.raw_root, state_root=foundation.state_root,
        history_start_date=values["history_start_date"], region=values["region"], lookback_days=values["lookback_days"],
        max_repair_items_per_incremental=values["max_repair_items_per_incremental"], request_min_interval_ms=values["request_min_interval_ms"],
        request_timeout_seconds=values["request_timeout_seconds"], max_attempts=values["max_attempts"], retry_base_seconds=values["retry_base_seconds"],
        retry_max_seconds=values["retry_max_seconds"], inline_retry_after_max_seconds=values["inline_retry_after_max_seconds"],
    )
