#!/usr/bin/env python3
"""Fetch Christian places of worship in Hot Springs, AR from OpenStreetMap."""

from __future__ import annotations

import argparse
import json
import pathlib
import urllib.parse
import urllib.request
from datetime import datetime, timezone

OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]
HOT_SPRINGS_RELATION_ID = 130675  # documented reference; area query uses name + admin_level

# Approximate Hot Springs, AR city limits — filters other U.S. places named "Hot Springs" in OSM.
CITY_BBOX = {
    "min_lat": 34.44,
    "max_lat": 34.57,
    "min_lon": -93.13,
    "max_lon": -92.97,
}

# Wider net: explicit christian tags plus untagged place_of_worship (filtered in Python).
QUERY = """
[out:json][timeout:90];
area["name"="Hot Springs"]["boundary"="administrative"]["admin_level"~"8|7"]->.searchArea;
(
  node["amenity"="place_of_worship"](area.searchArea);
  way["amenity"="place_of_worship"](area.searchArea);
);
out center tags;
"""

CHRISTIAN_RELIGIONS = {
    "christian", "christianity", "protestant", "catholic", "orthodox",
    "baptist", "methodist", "pentecostal", "lutheran", "presbyterian",
    "episcopal", "anglican", "nondenominational", "evangelical",
}
NON_CHRISTIAN_RELIGIONS = {
    "muslim", "islam", "jewish", "judaism", "buddhist", "buddhism",
    "hindu", "hinduism", "sikh", "sikhism", "mormon", "scientologist",
}


def fetch_overpass(query: str) -> dict:
    data = urllib.parse.urlencode({"data": query}).encode("utf-8")
    headers = {"User-Agent": "ParkerVale-ChurchMap/1.0 (info@parkerandvale.com)"}
    last_error = None
    for url in OVERPASS_URLS:
        request = urllib.request.Request(url, data=data, method="POST", headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as exc:  # noqa: BLE001 - try alternate Overpass endpoints
            last_error = exc
    raise RuntimeError(f"All Overpass endpoints failed: {last_error}")


def is_likely_christian(tags: dict) -> bool:
    religion = (tags.get("religion") or "").lower().strip()
    if religion in NON_CHRISTIAN_RELIGIONS:
        return False
    if religion in CHRISTIAN_RELIGIONS or religion.startswith("christian"):
        return True
    if religion:
        return False
    denomination = (tags.get("denomination") or "").lower()
    if denomination:
        return True
    name = (tags.get("name") or "").lower()
    church_words = ("church", "chapel", "parish", "ministry", "baptist", "methodist", "catholic")
    return any(word in name for word in church_words)


def in_city_bbox(lat: float | None, lon: float | None) -> bool:
    if lat is None or lon is None:
        return False
    return (
        CITY_BBOX["min_lat"] <= lat <= CITY_BBOX["max_lat"]
        and CITY_BBOX["min_lon"] <= lon <= CITY_BBOX["max_lon"]
    )


def parse_element(el: dict) -> dict | None:
    tags = el.get("tags", {})
    if not is_likely_christian(tags):
        return None

    if el["type"] == "node":
        lat, lon = el.get("lat"), el.get("lon")
    else:
        center = el.get("center", {})
        lat, lon = center.get("lat"), center.get("lon")

    if lat is None or lon is None:
        return None
    if not in_city_bbox(lat, lon):
        return None

    addr_parts = [
        tags.get("addr:housenumber", ""),
        tags.get("addr:street", ""),
    ]
    address = " ".join(part for part in addr_parts if part).strip()

    return {
        "osm_id": el.get("id"),
        "osm_type": el.get("type"),
        "name": tags.get("name", "Unnamed"),
        "denomination_raw": tags.get("denomination", ""),
        "religion": tags.get("religion", ""),
        "addr_housenumber": tags.get("addr:housenumber", ""),
        "addr_street": tags.get("addr:street", ""),
        "addr_city": tags.get("addr:city", ""),
        "address": address,
        "lat": lat,
        "lon": lon,
        "start_date": tags.get("start_date", ""),
        "website": tags.get("website", ""),
        "phone": tags.get("phone", ""),
        "opening_hours": tags.get("opening_hours", ""),
        "building": tags.get("building", ""),
        "wikidata": tags.get("wikidata", ""),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch Hot Springs churches from OSM.")
    parser.add_argument("--output", default="../data/raw/osm_churches.json")
    args = parser.parse_args()

    script_dir = pathlib.Path(__file__).resolve().parent
    output_path = pathlib.Path(args.output)
    if not output_path.is_absolute():
        output_path = script_dir / output_path
    output_path.parent.mkdir(parents=True, exist_ok=True)

    print("Querying Overpass API for Hot Springs, AR places of worship...")
    data = fetch_overpass(QUERY)
    churches = []
    skipped = 0
    for el in data.get("elements", []):
        parsed = parse_element(el)
        if parsed:
            churches.append(parsed)
        else:
            skipped += 1

    lats = [c["lat"] for c in churches]
    lons = [c["lon"] for c in churches]
    payload = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "source": "OpenStreetMap Overpass API",
        "boundary": "Hot Springs, AR city limits (admin_level=8)",
        "boundary_relation_id": HOT_SPRINGS_RELATION_ID,
        "element_count": len(data.get("elements", [])),
        "church_count": len(churches),
        "skipped_non_christian": skipped,
        "bbox": {
            "min_lat": min(lats) if lats else None,
            "max_lat": max(lats) if lats else None,
            "min_lon": min(lons) if lons else None,
            "max_lon": max(lons) if lons else None,
        },
        "churches": churches,
    }

    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Found {len(churches)} Christian places of worship (skipped {skipped} non-Christian/ambiguous).")
    print(f"Wrote {output_path}")
    if churches:
        print(f"Bounding box: {payload['bbox']}")


if __name__ == "__main__":
    main()
