from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any


class FitDataMessage:
    name: str
    fields: Sequence[Any]


class FitReader:
    def __init__(self, source: str | Path, *, check_crc: bool = ...) -> None: ...
    def __enter__(self) -> FitReader: ...
    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None: ...
    def __iter__(self) -> Iterator[Any]: ...
