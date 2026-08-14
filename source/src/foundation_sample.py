"""Compatibility facade for the synthetic Foundation sample API."""

from .foundation.sample import (
    build_acceptance_manifest,
    generate_sample_database,
    run_final_acceptance,
    scan_sample_privacy,
)

__all__ = [
    "build_acceptance_manifest",
    "generate_sample_database",
    "run_final_acceptance",
    "scan_sample_privacy",
]
