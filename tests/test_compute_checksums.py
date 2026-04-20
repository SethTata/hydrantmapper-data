# tests/test_compute_checksums.py
from __future__ import annotations

import hashlib
import json

from scripts.compute_checksums import compute_sha256, update_manifest_checksums


def test_compute_sha256_matches_hashlib(tmp_path):
    data = b"hello world\n"
    path = tmp_path / "file.txt"
    path.write_bytes(data)

    expected = hashlib.sha256(data).hexdigest()
    assert compute_sha256(path) == expected


def test_compute_sha256_streams_large_files(tmp_path):
    # 10 MB file — well over the default chunk boundary.
    data = b"x" * (10 * 1024 * 1024)
    path = tmp_path / "big.bin"
    path.write_bytes(data)
    assert compute_sha256(path) == hashlib.sha256(data).hexdigest()


def test_update_manifest_populates_checksums_and_sizes(write_pack):
    pack_dir = write_pack("check-ma", has_hydrants=True)
    update_manifest_checksums(pack_dir)

    manifest = json.loads((pack_dir / "manifest.json").read_text())
    for filename, entry in manifest["files"].items():
        actual_bytes = (pack_dir / filename).read_bytes()
        assert entry["size_bytes"] == len(actual_bytes)
        assert entry["sha256"] == hashlib.sha256(actual_bytes).hexdigest()


def test_update_manifest_is_idempotent(write_pack):
    pack_dir = write_pack("idem-ma", has_hydrants=True)
    update_manifest_checksums(pack_dir)
    first = (pack_dir / "manifest.json").read_text()
    update_manifest_checksums(pack_dir)
    second = (pack_dir / "manifest.json").read_text()
    assert first == second


def test_update_manifest_skips_files_not_on_disk(write_pack):
    # If the manifest lists a file that isn't present, compute_checksums
    # should raise rather than silently skip — we want loud failures.
    pack_dir = write_pack("partial-ma")
    manifest_path = pack_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["files"]["hydrants.csv"] = {"size_bytes": 0, "sha256": ""}
    manifest_path.write_text(json.dumps(manifest))

    import pytest
    with pytest.raises(FileNotFoundError):
        update_manifest_checksums(pack_dir)
