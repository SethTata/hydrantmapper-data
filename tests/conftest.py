# tests/conftest.py
from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.fixture
def tmp_jurisdictions_root(tmp_path: Path) -> Path:
    """Returns a tmp directory shaped like `jurisdictions/` with nothing in it."""
    root = tmp_path / "jurisdictions"
    root.mkdir()
    return root


@pytest.fixture
def sample_intersections_json() -> dict:
    """Minimal intersections.json that satisfies the extractor's invariants:
    two intersections, each with distinct streets, bbox fits."""
    return {
        "schema_version": 1,
        "jurisdiction": "sample-ma",
        "intersections": [
            {
                "name": "Main St & Oak Ave",
                "latitude": 42.4100,
                "longitude": -71.0100,
                "streets": ["Main St", "Oak Ave"],
            },
            {
                "name": "Main St & Elm St",
                "latitude": 42.4200,
                "longitude": -71.0200,
                "streets": ["Main St", "Elm St"],
            },
        ],
    }


@pytest.fixture
def write_pack(tmp_jurisdictions_root: Path, sample_intersections_json: dict):
    """Factory fixture: given a slug + manifest overrides + optional files,
    writes a complete pack dir and returns its path."""

    def _write(
        slug: str,
        *,
        has_hydrants: bool = False,
        hydrants_csv: str | None = None,
        manifest_overrides: dict | None = None,
    ) -> Path:
        pack_dir = tmp_jurisdictions_root / slug
        pack_dir.mkdir()

        # intersections.json
        (pack_dir / "intersections.json").write_text(
            json.dumps(sample_intersections_json, indent=2) + "\n"
        )

        files_entry = {
            "intersections.json": {"size_bytes": 0, "sha256": ""},
        }

        if has_hydrants:
            csv_text = hydrants_csv or "facility_id,latitude,longitude\n1,42.41,-71.01\n"
            (pack_dir / "hydrants.csv").write_text(csv_text)
            files_entry["hydrants.csv"] = {"size_bytes": 0, "sha256": ""}

        manifest = {
            "schema_version": 1,
            "jurisdiction": slug,
            "display_name": slug.split("-")[0].title(),
            "state": "MA",
            "last_updated": "2026-04-19T00:00:00Z",
            "version": 1,
            "bbox": [42.40, -71.02, 42.46, -70.98],
            "state_plane_zone": 4151,
            "has_hydrants": has_hydrants,
            "files": files_entry,
        }
        if manifest_overrides:
            manifest.update(manifest_overrides)

        (pack_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        return pack_dir

    return _write
