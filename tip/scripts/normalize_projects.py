#!/usr/bin/env python3
"""Normalize raw TxDOT project GeoJSON for the TIP tracker website."""

from __future__ import annotations

import argparse
import json
import pathlib
from datetime import datetime, timezone
from typing import Any


SOURCE_URL = "https://services.arcgis.com/KTcxiTD9dsQw4r7Z/ArcGIS/rest/services/TxDOT_Projects/FeatureServer/0"
PROJECT_TRACKER_URL = "https://www.txdot.gov/projects/project-tracker.html"


def first_value(props: dict[str, Any], *names: str, default: Any = None) -> Any:
    for name in names:
        value = props.get(name)
        if value not in (None, ""):
            return value
    return default


def normalize_phase(value: str | None) -> str:
    text = (value or "").lower()
    if "underway" in text or "begins soon" in text:
        return "Underway"
    if "within 4" in text or "within four" in text:
        return "Four-Year"
    if "5 to 10" in text or "5 - 10" in text:
        return "Five-to-Ten"
    if "corridor" in text or "10+" in text:
        return "Corridor Study"
    return "Planning"


def infer_category(props: dict[str, Any]) -> str:
    work = str(first_value(props, "TYPE_OF_WORK", default="")).lower()
    highway = str(first_value(props, "HIGHWAY_NUMBER", default="")).upper()
    freight = str(first_value(props, "FREIGHT", default="")).upper() == "Y"

    if freight or "freight" in work or "port" in work:
        return "Freight"
    if "bridge" in work or "crash wall" in work:
        return "Bridge"
    if any(term in work for term in ["safety", "crash", "signal", "intersection", "shoulder", "rumble"]):
        return "Safety"
    if any(term in work for term in ["sidewalk", "pedestrian", "bicycle", "shared use", "trail"]):
        return "Bike/Ped"
    if any(term in work for term in ["bus", "transit", "park and ride"]):
        return "Transit"
    if highway.startswith(("IH", "I ", "US", "SH", "SL", "LP", "FM")):
        return "Highway"
    return "Highway"


def cost_to_millions(value: Any) -> float:
    try:
        return round(float(value or 0) / 1_000_000, 2)
    except (TypeError, ValueError):
        return 0.0


def title_case_work(value: str) -> str:
    if not value:
        return "Transportation Project"
    return " ".join(word if word.isupper() and len(word) <= 4 else word.capitalize() for word in value.split())


def coords_to_leaflet_lines(geometry: dict[str, Any] | None) -> list[list[list[float]]]:
    if not geometry:
        return []

    geom_type = geometry.get("type")
    coords = geometry.get("coordinates")
    if geom_type == "LineString":
        return [[to_lat_lng(point) for point in coords]]
    if geom_type == "MultiLineString":
        return [[to_lat_lng(point) for point in line] for line in coords]
    return []


def to_lat_lng(point: list[float]) -> list[float]:
    lon, lat = point[:2]
    return [lat, lon]


def normalize_feature(feature: dict[str, Any]) -> dict[str, Any] | None:
    props = feature.get("properties", {})
    geometry = feature.get("geometry")
    lines = coords_to_leaflet_lines(geometry)
    if not lines:
        return None

    project_id = str(first_value(props, "PROJECT_ID", "CONTROL_SECT_JOB", default="Unknown"))
    highway = str(first_value(props, "HIGHWAY_NUMBER", default="Route TBD"))
    county = str(first_value(props, "COUNTY_NAME", default="Unknown"))
    district = str(first_value(props, "DISTRICT_NAME", default="Unknown"))
    work = str(first_value(props, "TYPE_OF_WORK", default="Transportation Project"))
    phase_raw = str(first_value(props, "PT_PHASE", default="Planning"))
    fiscal_year = first_value(props, "ESTMTD_FISCAL_YR", default="TBD")
    let_date = first_value(props, "PRJ_ESMTD_LET_D", default=None)
    limits_from = first_value(props, "LIMITS_FROM", default="")
    limits_to = first_value(props, "LIMITS_TO", default="")

    limits = " to ".join(part for part in [limits_from, limits_to] if part)
    title = f"{highway} - {title_case_work(work)}"
    description_parts = [title_case_work(work)]
    if limits:
        description_parts.append(f"Limits: {limits}.")
    description_parts.append(f"Current TxDOT project phase: {phase_raw}.")

    return {
        "id": project_id,
        "name": title,
        "highway": highway,
        "county": county,
        "district": district,
        "sponsor": f"TxDOT {district} District",
        "category": infer_category(props),
        "phase": normalize_phase(phase_raw),
        "funding": "TxDOT public project data",
        "fiscalYear": f"FY {fiscal_year}" if fiscal_year != "TBD" else "TBD",
        "cost": cost_to_millions(first_value(props, "EST_CONSTRUCTION_COST", default=0)),
        "status": str(first_value(props, "PROJ_STAT", default=phase_raw)),
        "letDate": let_date,
        "sourceUrl": PROJECT_TRACKER_URL,
        "description": " ".join(description_parts),
        "geometry": lines[0],
        "geometryParts": lines,
        "properties": {
            "control_section_job": first_value(props, "CONTROL_SECT_JOB"),
            "mpo": first_value(props, "MPO_NM"),
            "project_stage": first_value(props, "PROJ_STG"),
            "project_length": first_value(props, "PROJ_LENGTH"),
            "nhs": first_value(props, "NHS_FLAG"),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Normalize TxDOT raw GeoJSON into dashboard GeoJSON.")
    parser.add_argument("--input", default="../data/raw/txdot_projects_raw.geojson")
    parser.add_argument("--output", default="../data/projects.geojson")
    parser.add_argument("--metadata", default="../data/metadata.json")
    args = parser.parse_args()

    script_dir = pathlib.Path(__file__).resolve().parent
    input_path = pathlib.Path(args.input)
    output_path = pathlib.Path(args.output)
    metadata_path = pathlib.Path(args.metadata)
    if not input_path.is_absolute():
        input_path = script_dir / input_path
    if not output_path.is_absolute():
        output_path = script_dir / output_path
    if not metadata_path.is_absolute():
        metadata_path = script_dir / metadata_path

    raw = json.loads(input_path.read_text(encoding="utf-8"))
    projects = [project for feature in raw.get("features", []) if (project := normalize_feature(feature))]

    collection = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[lng_lat[1], lng_lat[0]] for lng_lat in project["geometry"]],
                },
                "properties": project,
            }
            for project in projects
        ],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(collection, indent=2), encoding="utf-8")

    source_meta = raw.get("properties", {})
    metadata = {
        "name": "Corpus Christi MPO TIP Tracker Demo",
        "source": "TxDOT Projects FeatureServer",
        "source_url": SOURCE_URL,
        "project_tracker_url": PROJECT_TRACKER_URL,
        "raw_where": source_meta.get("where"),
        "raw_fetched_at": source_meta.get("fetched_at"),
        "normalized_at": datetime.now(timezone.utc).isoformat(),
        "record_count": len(projects),
        "notes": "Public TxDOT project records normalized into Parker & Vale's dashboard schema. Review before using for official public reporting.",
    }
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(f"Wrote {len(projects)} normalized projects to {output_path}")
    print(f"Wrote metadata to {metadata_path}")


if __name__ == "__main__":
    main()
