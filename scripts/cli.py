# scripts/cli.py
"""One-shot CLI that callers (developer + CI) use to run the publishing
pipeline. Each subcommand is idempotent and safe to rerun.

Usage:
    python -m scripts.cli validate-all
    python -m scripts.cli checksums
    python -m scripts.cli registry
    python -m scripts.cli run-all
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from scripts.compute_checksums import update_all as update_checksums_all
from scripts.generate_registry import generate_registry
from scripts.validate_pack import validate_all


REPO_ROOT = Path(__file__).resolve().parent.parent
JURISDICTIONS_ROOT = REPO_ROOT / "jurisdictions"
REGISTRY_PATH = REPO_ROOT / "jurisdictions.json"


def cmd_validate_all() -> int:
    results = validate_all(JURISDICTIONS_ROOT)
    total_errors = 0
    for slug, errors in results.items():
        if errors:
            total_errors += len(errors)
            print(f"[FAIL] {slug}")
            for e in errors:
                print(f"  - {e}")
        else:
            print(f"[ OK ] {slug}")
    if total_errors:
        print(f"\n{total_errors} error(s) across {sum(1 for v in results.values() if v)} pack(s).")
        return 1
    print(f"\nAll {len(results)} pack(s) valid.")
    return 0


def cmd_checksums() -> int:
    update_checksums_all(JURISDICTIONS_ROOT)
    print(f"Checksums updated for all packs under {JURISDICTIONS_ROOT}.")
    return 0


def cmd_registry() -> int:
    generate_registry(JURISDICTIONS_ROOT, REGISTRY_PATH)
    print(f"Registry written to {REGISTRY_PATH}.")
    return 0


def cmd_run_all() -> int:
    rc = cmd_validate_all()
    if rc != 0:
        return rc
    rc = cmd_checksums()
    if rc != 0:
        return rc
    return cmd_registry()


def main() -> int:
    parser = argparse.ArgumentParser(prog="scripts.cli")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("validate-all")
    sub.add_parser("checksums")
    sub.add_parser("registry")
    sub.add_parser("run-all")

    args = parser.parse_args()
    return {
        "validate-all": cmd_validate_all,
        "checksums": cmd_checksums,
        "registry": cmd_registry,
        "run-all": cmd_run_all,
    }[args.cmd]()


if __name__ == "__main__":
    sys.exit(main())
