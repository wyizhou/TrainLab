"""Public Garmin collection tool assembled from focused collaborators."""

from __future__ import annotations

from .activities import ActivityCollectionMixin
from .base import GarminCollectionBase
from .fit import FitCollectionMixin
from .health import HealthCollectionMixin
from .repair import RepairAuditMixin


class GarminCollectionTool(
    RepairAuditMixin,
    FitCollectionMixin,
    ActivityCollectionMixin,
    HealthCollectionMixin,
    GarminCollectionBase,
):
    """One-shot Garmin collection API.

    Method resolution intentionally combines operational lifecycle, health,
    activity/FIT and repair responsibilities without changing the public tool
    surface used by callers and tests.
    """
