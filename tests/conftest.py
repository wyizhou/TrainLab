from __future__ import annotations

import copy
import shutil
from dataclasses import replace
from pathlib import Path

import pytest

from trainlab.config import Settings, load_settings
from trainlab.ingest import ingest_once


def make_settings(base: Settings, temporary: Path, *, fit_directory: Path | None = None, workbook: Path | None = None) -> Settings:
    values = copy.deepcopy(base.values)
    values["paths"].update(
        {
            "database": str(temporary / "data.db"),
            "state_directory": str(temporary / "state"),
            "log_directory": str(temporary / "logs"),
            "health_workbook": str(workbook or base.path("health_workbook")),
            "fit_directory": str(fit_directory or base.path("fit_directory")),
        }
    )
    (temporary / "state").mkdir(parents=True, exist_ok=True)
    (temporary / "logs").mkdir(parents=True, exist_ok=True)
    return replace(base, values=values)


@pytest.fixture(scope="session")
def base_settings() -> Settings:
    return load_settings()


@pytest.fixture(scope="session")
def golden_settings(base_settings: Settings) -> Settings:
    values = copy.deepcopy(base_settings.values)
    values["paths"]["health_workbook"] = str(base_settings.root / "test_data" / "Health.xlsx")
    values["paths"]["fit_directory"] = str(base_settings.root / "test_data")
    return replace(base_settings, values=values)


@pytest.fixture(scope="session")
def ingested_snapshot(golden_settings: Settings, tmp_path_factory) -> Path:
    temporary = tmp_path_factory.mktemp("golden-db")
    settings = make_settings(golden_settings, temporary)
    result = ingest_once(settings)
    assert result.failed_files == 0
    return settings.database_path


@pytest.fixture
def settings(golden_settings: Settings, ingested_snapshot: Path, tmp_path: Path) -> Settings:
    current = make_settings(golden_settings, tmp_path)
    shutil.copy2(ingested_snapshot, current.database_path)
    return current
