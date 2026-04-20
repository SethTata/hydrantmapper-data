# tests/test_validate_pack.py
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.validate_pack import validate_pack


def test_valid_pack_returns_no_errors(write_pack):
    pack_dir = write_pack("valid-ma")
    assert validate_pack(pack_dir) == []


def test_missing_manifest_is_error(tmp_jurisdictions_root: Path):
    pack_dir = tmp_jurisdictions_root / "nomanifest-ma"
    pack_dir.mkdir()
    errors = validate_pack(pack_dir)
    assert any("manifest.json" in e for e in errors)


def test_unsupported_schema_version_is_error(write_pack):
    pack_dir = write_pack("future-ma", manifest_overrides={"schema_version": 999})
    errors = validate_pack(pack_dir)
    assert any("schema_version" in e for e in errors)


def test_missing_required_field_is_error(write_pack):
    pack_dir = write_pack("broken-ma")
    manifest_path = pack_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    del manifest["bbox"]
    manifest_path.write_text(json.dumps(manifest))
    errors = validate_pack(pack_dir)
    assert any("bbox" in e for e in errors)


def test_has_hydrants_mismatch_is_error(write_pack):
    # Claims has_hydrants=True but hydrants.csv is not present in files map.
    pack_dir = write_pack("mismatch-ma", manifest_overrides={"has_hydrants": True})
    errors = validate_pack(pack_dir)
    assert any("has_hydrants" in e for e in errors)


def test_file_in_manifest_but_missing_on_disk_is_error(write_pack):
    pack_dir = write_pack("ghost-ma")
    manifest_path = pack_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["files"]["hydrants.csv"] = {"size_bytes": 100, "sha256": "abc"}
    manifest["has_hydrants"] = True
    manifest_path.write_text(json.dumps(manifest))
    errors = validate_pack(pack_dir)
    assert any("hydrants.csv" in e for e in errors)


def test_bbox_wrong_length_is_error(write_pack):
    pack_dir = write_pack("badbbox-ma", manifest_overrides={"bbox": [1, 2, 3]})
    errors = validate_pack(pack_dir)
    assert any("bbox" in e for e in errors)


def test_bbox_inverted_is_error(write_pack):
    # minLat > maxLat
    pack_dir = write_pack("inverted-ma", manifest_overrides={"bbox": [42.5, -71.0, 42.4, -70.9]})
    errors = validate_pack(pack_dir)
    assert any("bbox" in e for e in errors)


def test_slug_mismatch_is_error(write_pack):
    pack_dir = write_pack("wrong-ma")
    manifest_path = pack_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["jurisdiction"] = "different-ma"
    manifest_path.write_text(json.dumps(manifest))
    errors = validate_pack(pack_dir)
    assert any("slug" in e.lower() or "jurisdiction" in e.lower() for e in errors)
