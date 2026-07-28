"""Public compatibility facade for the modular Foundation layer.

Consumers continue to import ``trainlab.foundation``.  Implementation modules
separate configuration safety, schema validation, storage lifecycle, encrypted
backup primitives, and synthetic-sample privacy checks without changing that
public boundary.
"""
from __future__ import annotations

import sys
import types

from . import core as _core
from .core import *  # noqa: F403
from .core import _PinnedConnection, _utc
from .schema import validate_schema_manifest


class _FoundationFacade(types.ModuleType):
    """Keep the tested package-level monkeypatch seam compatible with core."""

    _forwarded = {"_utc", "validate_schema_manifest"}

    def __setattr__(self, name: str, value: object) -> None:
        super().__setattr__(name, value)
        if name in self._forwarded:
            setattr(_core, name, value)


sys.modules[__name__].__class__ = _FoundationFacade

__all__ = [name for name in dir(_core) if not name.startswith("_")] + ["_PinnedConnection", "_utc"]
