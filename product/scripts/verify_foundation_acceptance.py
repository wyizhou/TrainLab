#!/usr/bin/env python3
"""Run the complete offline FND-12 acceptance in a new isolated directory."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from trainlab.foundation_sample import run_final_acceptance


parser=argparse.ArgumentParser(prog="verify_foundation_acceptance")
parser.add_argument("--output-root",required=True,type=Path)
args=parser.parse_args()
print(json.dumps(run_final_acceptance(args.output_root),sort_keys=True))
