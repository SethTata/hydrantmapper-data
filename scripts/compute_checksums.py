# scripts/compute_checksums.py
"""Compute SHA256 + byte-size for each file listed in a pack's manifest,
and write the results back into manifest.json. Idempotent — running it twice
produces identical output when inputs haven't changed.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

_CHUNK_SIZE = 64 * 1024  # 64 KB — matches stdlib default io buffer


def compute_sha256(path: Path) -> str:
    """Stream-hash a file. Constant memory regardless of file size."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(_CHUNK_SIZE), b""):
            h.update(chunk)
    return h.hexdigest()


def update_manifest_checksums(pack_dir: Path) -> None:
    """Update size_bytes + sha256 for every file in the manifest's 'files' map.

    Raises FileNotFoundError if a file declared in the manifest isn't on disk —
    that's a correctness failure that should stop CI, not a silent skip.
    """
    manifest_path = pack_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text())

    for filename in manifest["files"]:
        file_path = pack_dir / filename
        if not file_path.exists():
            raise FileNotFoundError(
                f"Pack {pack_dir.name}: file '{filename}' declared in manifest "
                f"but not found at {file_path}"
            )
        manifest["files"][filename] = {
            "size_bytes": file_path.stat().st_size,
            "sha256": compute_sha256(file_path),
        }

    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")


def update_all(jurisdictions_root: Path) -> None:
    for pack_dir in sorted(jurisdictions_root.iterdir()):
        if pack_dir.is_dir():
            update_manifest_checksums(pack_dir)
