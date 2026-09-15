"""Synthetic FIT summary timestamps independent of their elapsed-time bounds."""

from __future__ import annotations

import importlib

factory = importlib.import_module("m12_fit_factory")


def summary(
    kind=18, *, start=0, elapsed_ms=60417, stamp=0, timer_ms=None, sport=1, role=5
):
    fields = [(2, 0x86, factory.BASE + start), (253, 0x86, factory.BASE + stamp)]
    if elapsed_ms is not None:
        fields.append((7, 0x86, elapsed_ms))
    if timer_ms is not None:
        fields.append((8, 0x86, timer_ms))
    fields.append((5, 0, sport) if kind == 18 else (23, 0, role))
    return factory.message(kind, fields)


def activity(*, first=True, stamp=0, elapsed_ms=60417, laps=(), timer_ms=None):
    records = [
        factory.record(t, t * 3, 120, extra=[(0, 0x85, 1234567), (1, 0x85, 2345678)])
        for t in (0, 30, 60)
    ]
    summaries = [summary(stamp=stamp, elapsed_ms=elapsed_ms, timer_ms=timer_ms), *laps]
    return factory.file_bytes(summaries + records if first else records + summaries)
