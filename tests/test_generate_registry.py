# tests/test_generate_registry.py
from __future__ import annotations

import json
from pathlib import Path

from scripts.generate_registry import generate_registry


def test_empty_root_produces_empty_list(tmp_jurisdictions_root: Path):
    output = tmp_jurisdictions_root.parent / "jurisdictions.json"
    generate_registry(tmp_jurisdictions_root, output)
    registry = json.loads(output.read_text())
    assert registry["schema_version"] == 1
    assert registry["jurisdictions"] == []
    assert "generated_at" in registry


def test_single_pack_flattens_into_registry(write_pack):
    pack = write_pack("revere-ma", has_hydrants=True)
    output = pack.parent.parent / "jurisdictions.json"
    generate_registry(pack.parent, output)
    registry = json.loads(output.read_text())

    assert len(registry["jurisdictions"]) == 1
    entry = registry["jurisdictions"][0]
    assert entry["slug"] == "revere-ma"
    assert entry["display_name"] == "Revere"
    assert entry["state"] == "MA"
    assert entry["version"] == 1
    assert entry["has_hydrants"] is True
    assert entry["bbox"] == [42.40, -71.02, 42.46, -70.98]


def test_multiple_packs_sorted_alphabetically(write_pack):
    write_pack("winthrop-ma")
    write_pack("chelsea-ma")
    write_pack("revere-ma", has_hydrants=True)
    pack_parent = Path(write_pack("everett-ma").parent)
    output = pack_parent.parent / "jurisdictions.json"
    generate_registry(pack_parent, output)
    registry = json.loads(output.read_text())
    slugs = [j["slug"] for j in registry["jurisdictions"]]
    assert slugs == ["chelsea-ma", "everett-ma", "revere-ma", "winthrop-ma"]


def test_non_directory_siblings_are_ignored(write_pack, tmp_jurisdictions_root: Path):
    write_pack("revere-ma")
    (tmp_jurisdictions_root / "notes.txt").write_text("ignore me")
    output = tmp_jurisdictions_root.parent / "jurisdictions.json"
    generate_registry(tmp_jurisdictions_root, output)
    registry = json.loads(output.read_text())
    assert len(registry["jurisdictions"]) == 1


def test_generated_at_is_iso8601_utc(write_pack):
    write_pack("revere-ma")
    output = Path(write_pack("chelsea-ma").parent).parent / "jurisdictions.json"
    generate_registry(Path(write_pack("medford-ma").parent), output)
    registry = json.loads(output.read_text())
    # Shape: 2026-04-19T12:34:56Z
    assert registry["generated_at"].endswith("Z")
    assert "T" in registry["generated_at"]
    assert len(registry["generated_at"]) == 20
