#!/usr/bin/env python3
"""Fetch public TxDOT project records for the TIP tracker demo.

The default query pulls Corpus Christi MPO projects from TxDOT's public
Projects FeatureServer and stores the raw GeoJSON response locally. This keeps
the website fast and stable while still giving the demo a real public-data
pipeline.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import urllib.parse
import urllib.request
from datetime import datetime, timezone


SERVICE_URL = (
    "https://services.arcgis.com/KTcxiTD9dsQw4r7Z/ArcGIS/rest/services/"
    "TxDOT_Projects/FeatureServer/0/query"
)

DEFAULT_FIELDS = [
    "PROJECT_ID",
    "CONTROL_SECT_JOB",
    "DISTRICT_NAME",
    "COUNTY_NAME",
    "HIGHWAY_NUMBER",
    "TYPE_OF_WORK",
    "LIMITS_FROM",
    "LIMITS_TO",
    "PT_PHASE",
    "PROJ_STG",
    "PROJ_STAT",
    "ESTMTD_FISCAL_YR",
    "EST_CONSTRUCTION_COST",
    "MPO_NM",
    "PRJ_ESMTD_LET_D",
    "PROJ_LENGTH",
    "FREIGHT",
    "NHS_FLAG",
]


def build_where(args: argparse.Namespace) -> str:
    if args.where:
        return args.where

    clauses: list[str] = []
    if args.mpo:
        escaped = args.mpo.replace("'", "''")
        clauses.append(f"MPO_NM LIKE '%{escaped}%'")
    if args.district:
        escaped = args.district.replace("'", "''")
        clauses.append(f"DISTRICT_NAME = '{escaped}'")
    if args.counties:
        counties = [f"'{county.strip().replace("'", "''")}'" for county in args.counties.split(",") if county.strip()]
        if counties:
            clauses.append(f"COUNTY_NAME IN ({','.join(counties)})")

    return " AND ".join(clauses) if clauses else "1=1"


def fetch_geojson(where: str, limit: int) -> dict:
    params = {
        "f": "geojson",
        "where": where,
        "outFields": ",".join(DEFAULT_FIELDS),
        "returnGeometry": "true",
        "outSR": "4326",
        "resultRecordCount": str(limit),
        "orderByFields": "ESTMTD_FISCAL_YR ASC, EST_CONSTRUCTION_COST DESC",
    }
    url = f"{SERVICE_URL}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, headers={"User-Agent": "ParkerValeTIPDemo/1.0"})
    with urllib.request.urlopen(request, timeout=45) as response:
        return json.load(response)


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch TxDOT projects as raw GeoJSON.")
    parser.add_argument("--where", help="Custom ArcGIS SQL where clause. Overrides other filters.")
    parser.add_argument("--mpo", default="Corpus Christi", help="MPO_NM text to match. Default: Corpus Christi.")
    parser.add_argument("--district", help="Optional exact DISTRICT_NAME filter.")
    parser.add_argument("--counties", help="Optional comma-separated COUNTY_NAME filter.")
    parser.add_argument("--limit", type=int, default=500, help="Maximum records to fetch.")
    parser.add_argument(
        "--output",
        default="../data/raw/txdot_projects_raw.geojson",
        help="Output path, relative to this script or absolute.",
    )
    args = parser.parse_args()

    where = build_where(args)
    raw = fetch_geojson(where, args.limit)
    raw.setdefault("properties", {})
    raw["properties"].update(
        {
            "source": "TxDOT Projects FeatureServer",
            "source_url": SERVICE_URL,
            "where": where,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "record_count": len(raw.get("features", [])),
        }
    )

    output = pathlib.Path(args.output)
    if not output.is_absolute():
        output = pathlib.Path(__file__).resolve().parent / output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(raw, indent=2), encoding="utf-8")
    print(f"Wrote {len(raw.get('features', []))} records to {output}")
    print(f"Where: {where}")


if __name__ == "__main__":
    main()
