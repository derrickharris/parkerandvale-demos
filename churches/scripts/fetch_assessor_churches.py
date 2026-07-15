#!/usr/bin/env python3
"""Fetch likely church parcels in Hot Springs from Arkansas statewide assessor GIS."""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone

SOURCE_URL = (
    "https://gis.arkansas.gov/arcgis/rest/services/FEATURESERVICES/"
    "Planning_Cadastre/FeatureServer/0/query"
)

CHURCH_PATTERN = re.compile(
    r"\b(CHURCH|CHAPEL|PARISH|MINISTRY|CATHEDRAL|TABERNACLE|"
    r"BAPTIST|METHODIST|CATHOLIC|PENTECOSTAL|LUTHERAN|PRESBYTERIAN|"
    r"ASSEMBLY OF GOD|CHURCH OF GOD|CHURCH OF CHRIST|EPISCOPAL|"
    r"CHRISTIAN|CONGREGATION|DIOCESE)\b",
    re.IGNORECASE,
)


def build_where_clause() -> str:
    owner_checks = " OR ".join(
        f"UPPER(ownername) LIKE '%{token}%'"
        for token in (
            "CHURCH", "CHAPEL", "PARISH", "MINISTRY", "BAPTIST",
            "METHODIST", "CATHOLIC", "PENTECOSTAL", "LUTHERAN",
            "PRESBYTERAN", "EPISCOPAL", "CHRISTIAN", "CONGREGATION",
        )
    )
    legal_checks = " OR ".join(
        f"UPPER(parcellgl) LIKE '%{token}%'"
        for token in ("CHURCH", "CHAPEL", "PARISH", "MINISTRY")
    )
    return (
        "county = 'Garland' AND "
        "(UPPER(adrcity) LIKE '%HOT SPRINGS%' OR adrcity IS NULL) AND "
        f"(({owner_checks}) OR ({legal_checks}))"
    )


def fetch_page(where: str, offset: int, page_size: int = 200) -> dict:
    params = urllib.parse.urlencode({
        "where": where,
        "outFields": (
            "objectid,parcelid,ownername,parcellgl,adrlabel,adrnum,predir,"
            "pstrnam,pstrtype,psufdir,adrcity,adrzip5,assessvalue,totalvalue"
        ),
        "returnGeometry": "true",
        "outSR": "4326",
        "f": "json",
        "resultOffset": offset,
        "resultRecordCount": page_size,
    })
    url = f"{SOURCE_URL}?{params}"
    with urllib.request.urlopen(url, timeout=90) as response:
        return json.loads(response.read().decode("utf-8"))


def format_address(attrs: dict) -> str:
    if attrs.get("adrlabel"):
        return str(attrs["adrlabel"]).strip()
    parts = [
        str(attrs.get("adrnum") or ""),
        attrs.get("predir") or "",
        attrs.get("pstrnam") or "",
        attrs.get("pstrtype") or "",
        attrs.get("psufdir") or "",
    ]
    street = " ".join(part for part in parts if part).strip()
    city = attrs.get("adrcity") or "Hot Springs"
    zip5 = attrs.get("adrzip5")
    line = ", ".join(part for part in (street, city) if part)
    if zip5:
        line = f"{line} {zip5}".strip()
    return line


def parse_feature(feature: dict) -> dict | None:
    attrs = feature.get("attributes", {})
    owner = attrs.get("ownername") or ""
    legal = attrs.get("parcellgl") or ""
    haystack = f"{owner} {legal}"
    if not CHURCH_PATTERN.search(haystack):
        return None

    geometry = feature.get("geometry") or {}
    lon = geometry.get("x")
    lat = geometry.get("y")
    if lat is None or lon is None:
        return None

    return {
        "assessor_objectid": attrs.get("objectid"),
        "parcelid": attrs.get("parcelid", ""),
        "name": owner.strip() or legal.strip() or "Unnamed Parcel",
        "ownername": owner.strip(),
        "parcellgl": legal.strip(),
        "address": format_address(attrs),
        "adrcity": attrs.get("adrcity", ""),
        "lat": lat,
        "lon": lon,
        "assessvalue": attrs.get("assessvalue"),
        "totalvalue": attrs.get("totalvalue"),
    }


def fetch_all_candidates() -> list[dict]:
    where = build_where_clause()
    candidates: list[dict] = []
    offset = 0
    while True:
        payload = fetch_page(where, offset)
        if payload.get("error"):
            raise RuntimeError(payload["error"])

        features = payload.get("features", [])
        for feature in features:
            parsed = parse_feature(feature)
            if parsed:
                candidates.append(parsed)

        if not payload.get("exceededTransferLimit"):
            break
        offset += len(features)
        if not features:
            break

    return candidates


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch Garland County church parcels.")
    parser.add_argument("--output", default="../data/raw/assessor_candidates.json")
    args = parser.parse_args()

    script_dir = pathlib.Path(__file__).resolve().parent
    output_path = pathlib.Path(args.output)
    if not output_path.is_absolute():
        output_path = script_dir / output_path
    output_path.parent.mkdir(parents=True, exist_ok=True)

    print("Querying Arkansas GIS assessor parcels for Hot Springs church candidates...")
    candidates = fetch_all_candidates()
    payload = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "source": "Arkansas GIS Office Planning_Cadastre PARCEL_CENTROID_CAMP",
        "source_url": SOURCE_URL,
        "county": "Garland",
        "city_filter": "Hot Springs",
        "candidate_count": len(candidates),
        "candidates": candidates,
    }
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Found {len(candidates)} assessor church candidates.")
    print(f"Wrote {output_path}")


if __name__ == "__main__":
    main()
