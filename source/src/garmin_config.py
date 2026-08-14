"""Validated, schedule-free configuration for the one-shot Garmin tool."""

from __future__ import annotations

import json
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

from .foundation import FoundationConfig
from .garmin import GarminConfig
from .resources import resource_bytes


def load_garmin_config(
    project_root: Path, foundation: FoundationConfig | None = None
) -> GarminConfig:
    foundation = foundation or FoundationConfig.load(project_root)
    payload = yaml.safe_load(
        (project_root / "config" / "garmin.yaml").read_text(encoding="utf-8")
    )
    schema = json.loads(resource_bytes("harness/schemas/garmin_config.schema.json"))
    if list(Draft202012Validator(schema).iter_errors(payload)):
        raise ValueError("invalid_garmin_configuration")
    values = payload["garmin"]
    # ``token_store`` is a logical path rooted at Foundation's state role, not
    # a project-root-relative filesystem path.  The CLI resolves this fixed
    # locator to ``foundation.state_root / "secrets" / "garmin"``.  Keeping
    # the configured value exact prevents traversal or accidental alternate
    # credential locations while allowing Foundation's data_root to move.
    if Path(values["token_store"]).parts != ("state", "secrets", "garmin"):
        raise ValueError("invalid_garmin_token_store")
    return GarminConfig(
        database_path=foundation.database_path,
        raw_root=foundation.raw_root,
        state_root=foundation.state_root,
        history_start_date=values["history_start_date"],
        region=values["region"],
        lookback_days=values["lookback_days"],
        max_repair_items_per_incremental=values["max_repair_items_per_incremental"],
        request_min_interval_ms=values["request_min_interval_ms"],
        request_interval_jitter_ms=values["request_interval_jitter_ms"],
        request_timeout_seconds=values["request_timeout_seconds"],
        max_attempts=values["max_attempts"],
        retry_base_seconds=values["retry_base_seconds"],
        retry_max_seconds=values["retry_max_seconds"],
        inline_retry_after_max_seconds=values["inline_retry_after_max_seconds"],
        rate_limit_fallback_seconds=values["rate_limit_fallback_seconds"],
    )
