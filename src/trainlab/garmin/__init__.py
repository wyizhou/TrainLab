"""Garmin collection package with a stable compatibility facade.

The package intentionally continues to export the former ``trainlab.garmin``
API.  Focused modules own contracts, storage, collection domains and repair
operations; callers do not need to know that internal layout.
"""
from __future__ import annotations

import sys
import types

from . import activities as _activities
from . import base as _base
from . import contracts as _contracts
from . import fit as _fit
from . import health as _health
from . import repair as _repair
from . import repository as _repository
from .contracts import *  # noqa: F403
from .repository import GarminRepository
from .tool import GarminCollectionTool


_COMPATIBILITY_MODULES = (
    _contracts,
    _repository,
    _base,
    _health,
    _activities,
    _fit,
    _repair,
)


class _CompatibilityModule(types.ModuleType):
    """Keep documented monkeypatch seams stable while code is modularized."""

    def __setattr__(self, name: str, value: object) -> None:
        super().__setattr__(name, value)
        if not name.startswith("_"):
            for module in _COMPATIBILITY_MODULES:
                if hasattr(module, name):
                    setattr(module, name, value)


sys.modules[__name__].__class__ = _CompatibilityModule
