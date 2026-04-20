# scripts/validate_pack.py
"""Structural validation for a jurisdiction pack directory.

Returns a list of human-readable error strings. Empty list = valid.
Called from CI (via cli.py) before publishing.
"""
from __future__ import annotations

import json
from pathlib import Path

REQUIRED_FIELDS = [
    "schema_version",
    "jurisdiction",
    "display_name",
    "state",
    "last_updated",
    "version",
    "bbox",
    "state_plane_zone",
    "has_hydrants",
    "files",
]

SUPPORTED_SCHEMA_VERSIONS = {1}


def validate_pack(pack_dir: Path) -> list[str]:
    errors: list[str] = []
    manifest_path = pack_dir / "manifest.json"

    if not manifest_path.exists():
        errors.append(f"{pack_dir.name}: manifest.json is missing")
        return errors

    try:
        manifest = json.loads(manifest_path.read_text())
    except json.JSONDecodeError as exc:
        errors.append(f"{pack_dir.name}: manifest.json is not valid JSON ({exc})")
        return errors

    for field in REQUIRED_FIELDS:
        if field not in manifest:
            errors.append(f"{pack_dir.name}: manifest missing required field '{field}'")

    if errors:
        # Don't try to interpret a half-formed manifest.
        return errors

    schema_version = manifest["schema_version"]
    if schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        errors.append(
            f"{pack_dir.name}: unsupported schema_version {schema_version} "
            f"(supported: {sorted(SUPPORTED_SCHEMA_VERSIONS)})"
        )

    # Slug consistency: manifest.jurisdiction must match directory name.
    if manifest["jurisdiction"] != pack_dir.name:
        errors.append(
            f"{pack_dir.name}: manifest.jurisdiction='{manifest['jurisdiction']}' "
            f"does not match directory slug '{pack_dir.name}'"
        )

    # bbox structure.
    bbox = manifest["bbox"]
    if not isinstance(bbox, list) or len(bbox) != 4:
        errors.append(f"{pack_dir.name}: bbox must be a 4-element list [minLat, minLon, maxLat, maxLon]")
    else:
        min_lat, min_lon, max_lat, max_lon = bbox
        if min_lat >= max_lat:
            errors.append(f"{pack_dir.name}: bbox inverted — minLat {min_lat} >= maxLat {max_lat}")
        if min_lon >= max_lon:
            errors.append(f"{pack_dir.name}: bbox inverted — minLon {min_lon} >= maxLon {max_lon}")

    # files map must match what's actually on disk.
    declared_files = manifest["files"]
    for filename in declared_files:
        if not (pack_dir / filename).exists():
            errors.append(
                f"{pack_dir.name}: file '{filename}' declared in manifest but missing on disk"
            )

    # has_hydrants must agree with hydrants.csv presence.
    has_hydrants_declared = manifest["has_hydrants"]
    has_hydrants_actual = "hydrants.csv" in declared_files
    if has_hydrants_declared != has_hydrants_actual:
        errors.append(
            f"{pack_dir.name}: has_hydrants={has_hydrants_declared} but "
            f"hydrants.csv {'present' if has_hydrants_actual else 'absent'} in files map"
        )

    return errors


def validate_all(jurisdictions_root: Path) -> dict[str, list[str]]:
    """Validate every pack under jurisdictions_root. Returns {slug: [errors]}."""
    results: dict[str, list[str]] = {}
    for pack_dir in sorted(jurisdictions_root.iterdir()):
        if not pack_dir.is_dir():
            continue
        results[pack_dir.name] = validate_pack(pack_dir)
    return results
