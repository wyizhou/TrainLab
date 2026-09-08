from collections.abc import Iterator
from enum import Enum
from io import BytesIO
from pathlib import Path
from typing import Any, BinaryIO, Protocol

class CrcCheck(Enum):
    DISABLED = 0
    READONLY = 1
    WARN = 2
    RAISE = 3
    ENABLED = 3

class ErrorHandling(Enum):
    IGNORE = 0
    WARN = 1
    RAISE = 2

class _FieldData(Protocol):
    units: str | None

class FitDataMessage:
    name: str
    fields: list[Any]
    def get_field(self, field_name_or_num: str | int, idx: int = ...) -> _FieldData: ...
    def get_value(
        self,
        field_name_or_num: str | int,
        *,
        idx: int = ...,
        fallback: Any = ...,
        raw_value: bool = ...,
        fit_type: Any = ...,
        py_type: Any = ...,
    ) -> Any: ...

class FitReader:
    def __init__(
        self,
        source: str | Path | BinaryIO | BytesIO,
        *,
        check_crc: bool | CrcCheck = ...,
        error_handling: ErrorHandling = ...,
        processor: Any = ...,
        keep_raw_chunks: bool = ...,
        data_bag: Any = ...,
    ) -> None: ...
    def __enter__(self) -> FitReader: ...
    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None: ...
    def __iter__(self) -> Iterator[Any]: ...
