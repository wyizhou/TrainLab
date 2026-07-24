#!/usr/bin/env python3
"""Generate a new projection-only TrainLab synthetic sample database."""
from __future__ import annotations
import argparse
from pathlib import Path
from trainlab.foundation_sample import generate_sample_database

parser = argparse.ArgumentParser()
parser.add_argument("--output-root", required=True, type=Path)
args = parser.parse_args()
print(generate_sample_database(args.output_root))
