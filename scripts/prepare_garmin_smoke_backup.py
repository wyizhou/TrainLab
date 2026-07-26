#!/usr/bin/env python3
"""Create E-04 isolated backup evidence; prints one redacted JSON receipt."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
from trainlab.garmin_smoke_backup import GarminSmokeBackupError, prepare_backup

ROOT = Path(__file__).resolve().parents[1]
def main() -> int:
    parser = argparse.ArgumentParser(prog="prepare_garmin_smoke_backup")
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--key-file", required=True, type=Path)
    parser.add_argument("--authorization-id", required=True)
    parser.add_argument("--operator-registered", action="store_true")
    args = parser.parse_args()
    try:
        receipt = prepare_backup(project_root=ROOT, output_root=args.output_root, key_file=args.key_file, authorization_id=args.authorization_id, operator_registered=args.operator_registered)
    except Exception:
        print(json.dumps({"status": "failed", "code": "backup_preflight_failed"}, sort_keys=True)); return 2
    print(json.dumps(receipt, sort_keys=True)); return 0
if __name__ == "__main__": raise SystemExit(main())
