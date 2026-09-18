"""Configuration contracts that reference private files without reading secrets."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from trainlab.contracts.paths import AI_CONFIG_PATH, GARMIN_CONFIG_PATH

ConfigKind = Literal["ai", "garmin"]


@dataclass(frozen=True)
class ConfigFileContract:
    kind: ConfigKind
    relative_path: Path
    adapter_capabilities: tuple[str, ...]
    contains_secret_material: bool

    def public_summary(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "path": self.relative_path.as_posix(),
            "adapter_capabilities": list(self.adapter_capabilities),
            "contains_secret_material": self.contains_secret_material,
            "secret_values_redacted": True,
            "exact_private_key_names_frozen": False,
        }


AI_CONFIG_CONTRACT = ConfigFileContract(
    kind="ai",
    relative_path=AI_CONFIG_PATH,
    adapter_capabilities=("openai_compatible_base_url", "model_selection", "credential_reference"),
    contains_secret_material=True,
)

GARMIN_CONFIG_CONTRACT = ConfigFileContract(
    kind="garmin",
    relative_path=GARMIN_CONFIG_PATH,
    adapter_capabilities=("auth_store_reference", "refresh_when_available"),
    contains_secret_material=True,
)


def public_config_contracts() -> tuple[dict[str, object], ...]:
    return (AI_CONFIG_CONTRACT.public_summary(), GARMIN_CONFIG_CONTRACT.public_summary())
