# scripts/generate_registry.py
"""Flatten every per-pack manifest.json into the top-level jurisdictions.json
that the iOS client fetches at launch.

Keeps the bbox + has_hydrants fields in the registry so the mutual-aid
lookup (Phase D) and onboarding picker (Phase B) can avoid a manifest fetch.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 1


def generate_registry(jurisdictions_root: Path, output_path: Path) -> None:
    entries: list[dict] = []

    for pack_dir in sorted(jurisdictions_root.iterdir()):
        if not pack_dir.is_dir():
            continue

        manifest_path = pack_dir / "manifest.json"
        if not manifest_path.exists():
            # validate_pack catches this; skip here to avoid crashing
            # the publisher when a half-added pack is on disk.
            continue

        manifest = json.loads(manifest_path.read_text())
        entries.append({
            "slug": manifest["jurisdiction"],
            "display_name": manifest["display_name"],
            "state": manifest["state"],
            "version": manifest["version"],
            "bbox": manifest["bbox"],
            "has_hydrants": manifest["has_hydrants"],
        })

    registry = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _iso8601_utc_now(),
        "jurisdictions": entries,
    }

    output_path.write_text(json.dumps(registry, indent=2) + "\n")


def _iso8601_utc_now() -> str:
    """Fixed-width 'YYYY-MM-DDTHH:MM:SSZ' — no microseconds, always Z-terminated."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
