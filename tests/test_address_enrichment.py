from __future__ import annotations

import json

from scripts.address_enrichment import (
    AddressCandidate,
    IntersectionCandidate,
    confidence_for_distance,
    enrich_hydrant_rows,
    feature_to_address_candidate,
    load_intersections,
    promote_csv_to_pack,
)


def test_confidence_buckets_match_field_review_contract():
    assert confidence_for_distance(50) == "derived_0_50_ft"
    assert confidence_for_distance(51) == "derived_50_100_ft"
    assert confidence_for_distance(100) == "derived_50_100_ft"
    assert confidence_for_distance(101) == "derived_100_150_ft"
    assert confidence_for_distance(149) == "derived_100_150_ft"
    assert confidence_for_distance(150) == "intersection_preferred_150_plus_ft"


def test_enrichment_uses_nearest_address_when_label_is_close():
    rows = [
        {
            "facilityid": "BOS-1",
            "address": "14 (STREET_FEA 1)",
            "streetname": "STREET_FEA 1",
            "lon": "-71.000000",
            "lat": "42.000000",
        }
    ]
    addresses = [
        AddressCandidate(
            label="14 Main St",
            streetname="Main St",
            lat=42.000050,
            lon=-71.000000,
            source="test-address-source",
            source_id="SAM-14",
            point_type="Primary address",
        )
    ]

    enriched = enrich_hydrant_rows(rows, addresses, intersections=[])

    assert enriched[0]["address"] == "14 Main St"
    assert enriched[0]["streetname"] == "Main St"
    assert enriched[0]["nearest_address_label"] == "14 Main St"
    assert enriched[0]["address_source"] == "test-address-source"
    assert enriched[0]["address_source_id"] == "SAM-14"
    assert enriched[0]["address_label_type"] == "nearest_address"
    assert enriched[0]["address_confidence"] == "derived_0_50_ft"
    assert int(enriched[0]["address_distance_ft"]) < 50


def test_enrichment_prefers_intersection_label_when_address_is_too_far():
    rows = [
        {
            "facilityid": "CHEL-1",
            "address": "",
            "streetname": "",
            "lon": "-71.000000",
            "lat": "42.000000",
        }
    ]
    addresses = [
        AddressCandidate(
            label="200 Broadway",
            streetname="Broadway",
            lat=42.001000,
            lon=-71.000000,
            source="massgis-addresses",
            source_id="MA-200",
            point_type="Building",
        )
    ]
    intersections = [
        IntersectionCandidate(
            label="Broadway & Cross St",
            streetname="Broadway",
            lat=42.000050,
            lon=-71.000000,
        )
    ]

    enriched = enrich_hydrant_rows(rows, addresses, intersections=intersections)

    assert enriched[0]["address"] == "Near Broadway & Cross St"
    assert enriched[0]["streetname"] == "Broadway"
    assert enriched[0]["nearest_address_label"] == "200 Broadway"
    assert enriched[0]["nearest_intersection_label"] == "Broadway & Cross St"
    assert enriched[0]["address_label_type"] == "nearest_intersection"
    assert enriched[0]["address_confidence"] == "intersection_preferred_150_plus_ft"


def test_feature_to_address_candidate_accepts_boston_sam_fields():
    feature = {
        "attributes": {
            "FULL_ADDRESS": "14 Main St",
            "FULL_STREET_NAME": "Main St",
            "SAM_ADDRESS_ID": 123,
            "RELATIONSHIP_TYPE": 1,
        },
        "geometry": {"x": -71.0, "y": 42.0},
    }

    candidate = feature_to_address_candidate(feature, source="boston-sam")

    assert candidate == AddressCandidate(
        label="14 Main St",
        streetname="Main St",
        lat=42.0,
        lon=-71.0,
        source="boston-sam",
        source_id="123",
        point_type="Primary address",
    )


def test_feature_to_address_candidate_accepts_massgis_fields():
    feature = {
        "attributes": {
            "FULL_NUMBER_STANDARDIZED": "200",
            "STREET_NAME": "BROADWAY",
            "MASTER_ADDRESS_ID": "M-200",
            "POINT_TYPE": "Building",
        },
        "geometry": {"x": -71.0, "y": 42.0},
    }

    candidate = feature_to_address_candidate(feature, source="massgis-master-address-points")

    assert candidate == AddressCandidate(
        label="200 Broadway",
        streetname="Broadway",
        lat=42.0,
        lon=-71.0,
        source="massgis-master-address-points",
        source_id="M-200",
        point_type="Building",
    )


def test_load_intersections_accepts_street_index_schema(tmp_path):
    path = tmp_path / "intersections.json"
    path.write_text(
        """
        {
          "schema_version": 1,
          "jurisdiction": "sample-ma",
          "streets": {
            "main street": [
              {
                "name": "Oak Avenue",
                "class": "residential",
                "coord": [42.0, -71.0]
              }
            ]
          }
        }
        """,
        encoding="utf-8",
    )

    assert load_intersections(path) == [
        IntersectionCandidate(
            label="Main Street & Oak Avenue",
            streetname="Main Street",
            lat=42.0,
            lon=-71.0,
        )
    ]


def test_promote_csv_to_pack_adds_hydrant_file_to_cross_streets_pack(write_pack, tmp_path):
    pack_dir = write_pack("chelsea-ma")
    source = tmp_path / "hydrants.csv"
    source.write_text("facilityid,streetname,address,lon,lat\nHYD1,Broadway,10 Broadway,-71,42\n")

    promote_csv_to_pack(
        source,
        pack_dir,
        last_updated="2026-05-20T00:00:00Z",
        version=2,
    )

    assert (pack_dir / "hydrants.csv").read_text() == source.read_text()
    manifest = json.loads((pack_dir / "manifest.json").read_text())
    assert manifest["has_hydrants"] is True
    assert manifest["version"] == 2
    assert manifest["last_updated"] == "2026-05-20T00:00:00Z"
    assert manifest["files"]["hydrants.csv"] == {"size_bytes": 0, "sha256": ""}
