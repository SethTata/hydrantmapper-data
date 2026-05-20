# scripts/address_enrichment.py
"""Nearest-address enrichment for hydrant pack CSVs.

Adds firefighter-readable address labels while preserving audit fields that
show whether a label is a close address match or an intersection fallback.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import shutil
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import urlopen


BOSTON_SAM_ADDRESS_ENDPOINT = (
    "https://gisportal.boston.gov/arcgis/rest/services/SAM/"
    "Live_SAM_Address/FeatureServer/0"
)
MASSGIS_MASTER_ADDRESS_ENDPOINT = (
    "https://arcgisserver.digital.mass.gov/arcgisserver/rest/services/AGOL/"
    "MassGIS_Master_Address_Points/MapServer/0"
)

SOURCE_CONFIGS: dict[str, dict[str, str]] = {
    "boston-sam": {
        "endpoint": BOSTON_SAM_ADDRESS_ENDPOINT,
        "where": "RELATIONSHIP_TYPE = 1 AND FULL_ADDRESS IS NOT NULL",
        "out_fields": (
            "OBJECTID,SAM_ADDRESS_ID,RELATIONSHIP_TYPE,FULL_ADDRESS,"
            "FULL_STREET_NAME,STREET_NUMBER,STREET_BODY,STREET_FULL_SUFFIX"
        ),
    },
    "massgis-chelsea": {
        "endpoint": MASSGIS_MASTER_ADDRESS_ENDPOINT,
        "where": "GEOGRAPHIC_TOWN = 'CHELSEA'",
        "out_fields": (
            "OBJECTID,FULL_NUMBER_STANDARDIZED,STREET_NAME,BUILDING_NAME,"
            "GEOGRAPHIC_TOWN,COMMUNITY_NAME,PC_NAME,POSTCODE,POINT_TYPE,"
            "MASTER_ADDRESS_ID"
        ),
    },
}

ENRICHMENT_FIELDS = [
    "source_address",
    "source_streetname",
    "address_distance_ft",
    "address_confidence",
    "address_label_type",
    "address_source",
    "address_source_id",
    "nearest_address_label",
    "nearest_address_streetname",
    "nearest_address_lat",
    "nearest_address_lon",
    "nearest_intersection_label",
    "nearest_intersection_distance_ft",
]


@dataclass(frozen=True)
class AddressCandidate:
    label: str
    streetname: str
    lat: float
    lon: float
    source: str
    source_id: str
    point_type: str


@dataclass(frozen=True)
class IntersectionCandidate:
    label: str
    streetname: str
    lat: float
    lon: float


def confidence_for_distance(distance_ft: int) -> str:
    if distance_ft <= 50:
        return "derived_0_50_ft"
    if distance_ft <= 100:
        return "derived_50_100_ft"
    if distance_ft < 150:
        return "derived_100_150_ft"
    return "intersection_preferred_150_plus_ft"


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def human_title(value: Any) -> str:
    text = clean_text(value)
    if not text:
        return ""
    if text.upper() == text or text.lower() == text:
        return text.title()
    return text


def format_massgis_label(attrs: dict[str, Any]) -> str:
    number = clean_text(attrs.get("FULL_NUMBER_STANDARDIZED"))
    street = human_title(attrs.get("STREET_NAME"))
    label = " ".join(part for part in [number, street] if part)
    return label or human_title(attrs.get("BUILDING_NAME")) or street


def relationship_type_label(value: Any) -> str:
    if value == 1 or clean_text(value) == "1":
        return "Primary address"
    if value == 2 or clean_text(value) == "2":
        return "Secondary address"
    return clean_text(value)


def feature_to_address_candidate(feature: dict[str, Any], *, source: str) -> AddressCandidate | None:
    attrs = feature.get("attributes") or {}
    geometry = feature.get("geometry") or {}
    lon = geometry.get("x")
    lat = geometry.get("y")
    if lon is None or lat is None:
        return None

    label = clean_text(attrs.get("FULL_ADDRESS")) or format_massgis_label(attrs)
    streetname = (
        clean_text(attrs.get("FULL_STREET_NAME"))
        or human_title(attrs.get("STREET_NAME"))
        or human_title(attrs.get("STREET_BODY"))
    )
    if not label or not streetname:
        return None

    source_id = (
        clean_text(attrs.get("SAM_ADDRESS_ID"))
        or clean_text(attrs.get("MASTER_ADDRESS_ID"))
        or clean_text(attrs.get("OBJECTID"))
    )
    point_type = clean_text(attrs.get("POINT_TYPE")) or relationship_type_label(
        attrs.get("RELATIONSHIP_TYPE")
    )

    return AddressCandidate(
        label=label,
        streetname=streetname,
        lat=float(lat),
        lon=float(lon),
        source=source,
        source_id=source_id,
        point_type=point_type,
    )


def to_xy_feet(lat: float, lon: float, origin_lat: float) -> tuple[float, float]:
    feet_per_degree_lat = 364_000.0
    feet_per_degree_lon = feet_per_degree_lat * math.cos(math.radians(origin_lat))
    return lon * feet_per_degree_lon, lat * feet_per_degree_lat


def distance_ft(
    left_lat: float,
    left_lon: float,
    right_lat: float,
    right_lon: float,
    origin_lat: float,
) -> int:
    left_x, left_y = to_xy_feet(left_lat, left_lon, origin_lat)
    right_x, right_y = to_xy_feet(right_lat, right_lon, origin_lat)
    return round(math.hypot(right_x - left_x, right_y - left_y))


def row_coordinate(row: dict[str, str]) -> tuple[float, float]:
    lon = row.get("lon") or row.get("longitude")
    lat = row.get("lat") or row.get("latitude")
    if lon is None or lat is None:
        raise ValueError(f"{row.get('facilityid') or row.get('facility_id')}: missing coordinates")
    return float(lat), float(lon)


def nearest_address(
    lat: float,
    lon: float,
    addresses: list[AddressCandidate],
    origin_lat: float,
) -> tuple[AddressCandidate, int]:
    best = min(
        addresses,
        key=lambda candidate: distance_ft(lat, lon, candidate.lat, candidate.lon, origin_lat),
    )
    return best, distance_ft(lat, lon, best.lat, best.lon, origin_lat)


def nearest_intersection(
    lat: float,
    lon: float,
    intersections: list[IntersectionCandidate],
    origin_lat: float,
) -> tuple[IntersectionCandidate, int] | tuple[None, None]:
    if not intersections:
        return None, None
    best = min(
        intersections,
        key=lambda candidate: distance_ft(lat, lon, candidate.lat, candidate.lon, origin_lat),
    )
    return best, distance_ft(lat, lon, best.lat, best.lon, origin_lat)


def enrich_hydrant_rows(
    rows: list[dict[str, str]],
    addresses: list[AddressCandidate],
    *,
    intersections: list[IntersectionCandidate],
) -> list[dict[str, str]]:
    if not rows:
        return []
    if not addresses:
        raise ValueError("Address enrichment requires at least one address candidate")

    coordinates = [row_coordinate(row) for row in rows]
    origin_lat = sum(lat for lat, _ in coordinates) / len(coordinates)

    enriched: list[dict[str, str]] = []
    for row, (lat, lon) in zip(rows, coordinates):
        address, address_distance = nearest_address(lat, lon, addresses, origin_lat)
        intersection, intersection_distance = nearest_intersection(lat, lon, intersections, origin_lat)
        confidence = confidence_for_distance(address_distance)
        use_intersection = confidence == "intersection_preferred_150_plus_ft" and intersection is not None

        record = dict(row)
        record["source_address"] = clean_text(row.get("address"))
        record["source_streetname"] = clean_text(row.get("streetname"))
        record["address_distance_ft"] = str(address_distance)
        record["address_confidence"] = confidence
        record["address_source"] = address.source
        record["address_source_id"] = address.source_id
        record["nearest_address_label"] = address.label
        record["nearest_address_streetname"] = address.streetname
        record["nearest_address_lat"] = f"{address.lat:.8f}"
        record["nearest_address_lon"] = f"{address.lon:.8f}"

        if intersection is not None:
            record["nearest_intersection_label"] = intersection.label
            record["nearest_intersection_distance_ft"] = str(intersection_distance)
        else:
            record["nearest_intersection_label"] = ""
            record["nearest_intersection_distance_ft"] = ""

        if use_intersection:
            record["address"] = f"Near {intersection.label}"
            record["streetname"] = intersection.streetname
            record["address_label_type"] = "nearest_intersection"
        else:
            record["address"] = address.label
            record["streetname"] = address.streetname
            record["address_label_type"] = "nearest_address"

        enriched.append(record)

    return enriched


def load_csv_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def load_intersections(path: Path) -> list[IntersectionCandidate]:
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    intersections = []

    street_index = payload.get("streets")
    if isinstance(street_index, dict):
        seen: set[tuple[str, float, float]] = set()
        for primary_raw, neighbors in street_index.items():
            primary = human_title(primary_raw)
            if not isinstance(neighbors, list):
                continue
            for neighbor in neighbors:
                coord = neighbor.get("coord") if isinstance(neighbor, dict) else None
                secondary = human_title(neighbor.get("name")) if isinstance(neighbor, dict) else ""
                if not primary or not secondary or not isinstance(coord, list) or len(coord) != 2:
                    continue
                lat = float(coord[0])
                lon = float(coord[1])
                key = (f"{primary} & {secondary}", lat, lon)
                if key in seen:
                    continue
                seen.add(key)
                intersections.append(
                    IntersectionCandidate(
                        label=f"{primary} & {secondary}",
                        streetname=primary,
                        lat=lat,
                        lon=lon,
                    )
                )
        return intersections

    for item in payload.get("intersections", []):
        label = clean_text(item.get("name"))
        lat = item.get("latitude")
        lon = item.get("longitude")
        streets = item.get("streets") or []
        if not label or lat is None or lon is None:
            continue
        streetname = clean_text(streets[0]) if streets else label
        intersections.append(
            IntersectionCandidate(
                label=label,
                streetname=streetname,
                lat=float(lat),
                lon=float(lon),
            )
        )
    return intersections


def bbox_from_manifest(pack_dir: Path) -> list[float] | None:
    manifest_path = pack_dir / "manifest.json"
    if not manifest_path.exists():
        return None
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    bbox = manifest.get("bbox")
    if isinstance(bbox, list) and len(bbox) == 4:
        return [float(value) for value in bbox]
    return None


def fetch_json(url: str, params: dict[str, Any]) -> dict[str, Any]:
    query = urlencode(params)
    with urlopen(f"{url}?{query}", timeout=90) as response:
        return json.load(response)


def fetch_arcgis_features(
    endpoint: str,
    *,
    where: str,
    out_fields: str,
    bbox: list[float] | None,
    page_size: int = 2000,
) -> list[dict[str, Any]]:
    features: list[dict[str, Any]] = []
    offset = 0

    while True:
        params: dict[str, Any] = {
            "f": "json",
            "where": where,
            "outFields": out_fields,
            "returnGeometry": "true",
            "outSR": "4326",
            "resultOffset": offset,
            "resultRecordCount": page_size,
            "orderByFields": "OBJECTID",
        }
        if bbox is not None:
            min_lat, min_lon, max_lat, max_lon = bbox
            params.update(
                {
                    "geometry": f"{min_lon},{min_lat},{max_lon},{max_lat}",
                    "geometryType": "esriGeometryEnvelope",
                    "inSR": "4326",
                    "spatialRel": "esriSpatialRelIntersects",
                }
            )

        payload = fetch_json(f"{endpoint}/query", params)
        if "error" in payload:
            raise RuntimeError(json.dumps(payload["error"], indent=2))

        page = payload.get("features", [])
        features.extend(page)
        print(f"Fetched {len(page)} address points at offset {offset}", file=sys.stderr)

        if not payload.get("exceededTransferLimit") or not page:
            break

        offset += len(page)
        time.sleep(0.2)

    return features


def load_address_candidates(source_name: str, bbox: list[float] | None) -> list[AddressCandidate]:
    config = SOURCE_CONFIGS[source_name]
    features = fetch_arcgis_features(
        config["endpoint"],
        where=config["where"],
        out_fields=config["out_fields"],
        bbox=bbox,
    )
    candidates = [
        candidate
        for feature in features
        if (candidate := feature_to_address_candidate(feature, source=source_name)) is not None
    ]
    if not candidates:
        raise RuntimeError(f"No usable address candidates returned for {source_name}")
    return candidates


def output_fieldnames(input_fieldnames: list[str], rows: list[dict[str, str]]) -> list[str]:
    names = list(input_fieldnames)
    for row in rows:
        for key in row:
            if key not in names:
                names.append(key)
    for key in ENRICHMENT_FIELDS:
        if key not in names:
            names.append(key)
    return names


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def update_manifest_for_hydrants(pack_dir: Path, *, last_updated: str, version: int) -> None:
    manifest_path = pack_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["last_updated"] = last_updated
    manifest["version"] = version
    manifest["has_hydrants"] = True
    manifest.setdefault("files", {})["hydrants.csv"] = {"size_bytes": 0, "sha256": ""}
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def promote_csv_to_pack(source_csv: Path, pack_dir: Path, *, last_updated: str, version: int) -> None:
    if not source_csv.exists():
        raise FileNotFoundError(source_csv)
    shutil.copyfile(source_csv, pack_dir / "hydrants.csv")
    update_manifest_for_hydrants(pack_dir, last_updated=last_updated, version=version)


def summarize(rows: list[dict[str, str]]) -> str:
    buckets: dict[str, int] = {}
    for row in rows:
        confidence = row.get("address_confidence", "")
        buckets[confidence] = buckets.get(confidence, 0) + 1
    return ", ".join(f"{key}={buckets[key]}" for key in sorted(buckets))


def cmd_enrich_pack(args: argparse.Namespace) -> int:
    pack_dir = Path(args.pack)
    hydrants_path = pack_dir / "hydrants.csv"
    intersections_path = pack_dir / "intersections.json"
    if not hydrants_path.exists():
        raise FileNotFoundError(hydrants_path)

    input_fieldnames, rows = load_csv_rows(hydrants_path)
    bbox = bbox_from_manifest(pack_dir)
    addresses = load_address_candidates(args.source, bbox)
    intersections = load_intersections(intersections_path)
    enriched = enrich_hydrant_rows(rows, addresses, intersections=intersections)
    write_csv(Path(args.output), output_fieldnames(input_fieldnames, enriched), enriched)
    print(f"Wrote {len(enriched)} enriched hydrants to {args.output}")
    print(f"Confidence buckets: {summarize(enriched)}")
    return 0


def cmd_enrich_csv(args: argparse.Namespace) -> int:
    input_fieldnames, rows = load_csv_rows(Path(args.input))
    bbox = [float(value) for value in args.bbox.split(",")] if args.bbox else None
    addresses = load_address_candidates(args.source, bbox)
    intersections = load_intersections(Path(args.intersections)) if args.intersections else []
    enriched = enrich_hydrant_rows(rows, addresses, intersections=intersections)
    write_csv(Path(args.output), output_fieldnames(input_fieldnames, enriched), enriched)
    print(f"Wrote {len(enriched)} enriched hydrants to {args.output}")
    print(f"Confidence buckets: {summarize(enriched)}")
    return 0


def cmd_enrich_boston_root(args: argparse.Namespace) -> int:
    jurisdictions_root = Path(args.jurisdictions_root)
    output_root = Path(args.output_root) if args.output_root else None
    for pack_dir in sorted(jurisdictions_root.glob("boston-*")):
        hydrants_path = pack_dir / "hydrants.csv"
        if not pack_dir.is_dir() or not hydrants_path.exists():
            continue

        input_fieldnames, rows = load_csv_rows(hydrants_path)
        addresses = load_address_candidates("boston-sam", bbox_from_manifest(pack_dir))
        intersections = load_intersections(pack_dir / "intersections.json")
        enriched = enrich_hydrant_rows(rows, addresses, intersections=intersections)

        if args.in_place:
            output_path = hydrants_path
        else:
            if output_root is None:
                raise ValueError("--output-root is required unless --in-place is set")
            output_path = output_root / f"{pack_dir.name}-hydrants.csv"

        write_csv(output_path, output_fieldnames(input_fieldnames, enriched), enriched)
        if args.in_place:
            update_manifest_for_hydrants(
                pack_dir,
                last_updated=args.last_updated,
                version=args.version,
            )
        print(f"{pack_dir.name}: wrote {len(enriched)} rows to {output_path}")
        print(f"{pack_dir.name}: confidence buckets: {summarize(enriched)}")

    return 0


def cmd_promote_csv(args: argparse.Namespace) -> int:
    promote_csv_to_pack(
        Path(args.input),
        Path(args.pack),
        last_updated=args.last_updated,
        version=args.version,
    )
    print(f"Promoted {args.input} into {Path(args.pack) / 'hydrants.csv'}")
    return 0


def cmd_promote_boston_root(args: argparse.Namespace) -> int:
    input_root = Path(args.input_root)
    jurisdictions_root = Path(args.jurisdictions_root)
    promoted = 0
    for pack_dir in sorted(jurisdictions_root.glob("boston-*")):
        if not pack_dir.is_dir():
            continue
        source = input_root / f"{pack_dir.name}-hydrants.csv"
        promote_csv_to_pack(
            source,
            pack_dir,
            last_updated=args.last_updated,
            version=args.version,
        )
        promoted += 1
        print(f"Promoted {source} into {pack_dir / 'hydrants.csv'}")
    print(f"Promoted {promoted} Boston pack(s).")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="scripts.address_enrichment")
    sub = parser.add_subparsers(dest="cmd", required=True)

    enrich_pack = sub.add_parser("enrich-pack")
    enrich_pack.add_argument("--pack", required=True)
    enrich_pack.add_argument("--source", required=True, choices=sorted(SOURCE_CONFIGS))
    enrich_pack.add_argument("--output", required=True)
    enrich_pack.set_defaults(func=cmd_enrich_pack)

    enrich_csv = sub.add_parser("enrich-csv")
    enrich_csv.add_argument("--input", required=True)
    enrich_csv.add_argument("--source", required=True, choices=sorted(SOURCE_CONFIGS))
    enrich_csv.add_argument("--output", required=True)
    enrich_csv.add_argument("--intersections")
    enrich_csv.add_argument("--bbox", help="minLat,minLon,maxLat,maxLon")
    enrich_csv.set_defaults(func=cmd_enrich_csv)

    enrich_boston_root = sub.add_parser("enrich-boston-root")
    enrich_boston_root.add_argument("--jurisdictions-root", required=True)
    enrich_boston_root.add_argument("--output-root")
    enrich_boston_root.add_argument("--in-place", action="store_true")
    enrich_boston_root.add_argument("--last-updated", default="2026-05-20T00:00:00Z")
    enrich_boston_root.add_argument("--version", type=int, default=2)
    enrich_boston_root.set_defaults(func=cmd_enrich_boston_root)

    promote_csv = sub.add_parser("promote-csv")
    promote_csv.add_argument("--input", required=True)
    promote_csv.add_argument("--pack", required=True)
    promote_csv.add_argument("--last-updated", default="2026-05-20T00:00:00Z")
    promote_csv.add_argument("--version", type=int, default=2)
    promote_csv.set_defaults(func=cmd_promote_csv)

    promote_boston_root = sub.add_parser("promote-boston-root")
    promote_boston_root.add_argument("--input-root", required=True)
    promote_boston_root.add_argument("--jurisdictions-root", required=True)
    promote_boston_root.add_argument("--last-updated", default="2026-05-20T00:00:00Z")
    promote_boston_root.add_argument("--version", type=int, default=2)
    promote_boston_root.set_defaults(func=cmd_promote_boston_root)

    args = parser.parse_args()
    if getattr(args, "in_place", False) and args.output_root:
        parser.error("--output-root cannot be combined with --in-place")
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
