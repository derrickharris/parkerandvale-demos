#!/usr/bin/env python3
"""Normalize Ocala Marion TPO TIP line and point layers for the dashboard."""

from __future__ import annotations

import argparse
import json
import pathlib
import re
from datetime import datetime, timezone
from typing import Any


WEB_APP_URL = "https://marioncountyfl.maps.arcgis.com/apps/webappviewer/index.html?id=a1591413f8aa4cc7b2d78110c9b4e1a3"
TPO_TIP_URL = "https://ocalamariontpo.org/en/tip"


def money_to_millions(value: Any) -> float:
    if value in (None, ""):
        return 0.0
    text = str(value).replace("$", "").replace(",", "").strip()
    if text in {"", "-", "-   "}:
        return 0.0
    try:
        return round(float(text) / 1_000_000, 3)
    except ValueError:
        return 0.0


def first_value(props: dict[str, Any], *names: str, default: Any = None) -> Any:
    for name in names:
        value = props.get(name)
        if value not in (None, ""):
            return value
    return default


def infer_phase(props: dict[str, Any]) -> str:
    years = [
        ("FY 2026", money_to_millions(props.get("FY2026"))),
        ("FY 2027", money_to_millions(props.get("FY2027"))),
        ("FY 2028", money_to_millions(props.get("FY2028"))),
        ("FY 2029", money_to_millions(props.get("FY2029") or props.get("Field8"))),
        ("FY 2030", money_to_millions(props.get("FY2030"))),
    ]
    funded_years = [label for label, amount in years if amount > 0]
    if funded_years:
        return funded_years[0]
    if money_to_millions(props.get("FutureFunding")) > 0:
        return "Future"
    if money_to_millions(props.get("PriorTIPFunding")) > 0:
        return "Prior"
    return "Unfunded"


def infer_category(project_type: str) -> str:
    text = project_type.lower()
    if "bike" in text or "ped" in text or "trail" in text or "sidewalk" in text:
        return "Bike/Ped"
    if "transit" in text or "bus" in text or "suntran" in text:
        return "Transit"
    if "aviation" in text or "airport" in text:
        return "Aviation"
    if "interchange" in text:
        return "Interchange"
    if "safety" in text or "intersection" in text:
        return "Safety"
    if "capacity" in text or "roadway" in text or "resurfacing" in text:
        return "Roadway"
    return project_type or "Other"


def route_from_project(name: str) -> str:
    match = re.match(r"^([A-Z]{1,3}[- ]?\\d+|I-\\d+|US \\d+|SR \\d+|CR \\d+)", name)
    return match.group(1) if match else "Local"


def esri_geometry_to_dashboard(geometry: dict[str, Any] | None) -> tuple[str, list[Any]]:
    if not geometry:
        return "Unknown", []
    if "paths" in geometry:
        path = geometry["paths"][0]
        return "LineString", [[lat, lon] for lon, lat in path]
    if "x" in geometry and "y" in geometry:
        return "Point", [geometry["y"], geometry["x"]]
    return "Unknown", []


def geojson_geometry_to_dashboard(geometry: dict[str, Any] | None) -> tuple[str, list[Any]]:
    if not geometry:
        return "Unknown", []
    geom_type = geometry.get("type")
    coords = geometry.get("coordinates")
    if geom_type == "LineString":
        return "LineString", [[lat, lon] for lon, lat in coords]
    if geom_type == "MultiLineString":
        first_path = coords[0] if coords else []
        return "LineString", [[lat, lon] for lon, lat in first_path]
    if geom_type == "Point":
        lon, lat = coords[:2]
        return "Point", [lat, lon]
    return "Unknown", []


def dashboard_geometry_to_geojson(geometry_type: str, geometry: list[Any]) -> dict[str, Any]:
    if geometry_type == "Point":
        lat, lon = geometry
        return {"type": "Point", "coordinates": [lon, lat]}
    return {"type": "LineString", "coordinates": [[lon, lat] for lat, lon in geometry]}


def normalize_feature(feature: dict[str, Any], source_geometry_type: str) -> dict[str, Any] | None:
    props = feature.get("properties") or feature.get("attributes") or {}
    geometry_type, geometry = geojson_geometry_to_dashboard(feature.get("geometry"))
    if geometry_type == "Unknown":
        geometry_type, geometry = esri_geometry_to_dashboard(feature.get("geometry"))
    if geometry_type == "Unknown" or not geometry:
        return None

    project_number = str(first_value(props, "ProjectNumber", "FM", "FM_1", default="Unknown"))
    name = str(first_value(props, "Project", default="Ocala Marion TIP Project"))
    description = str(first_value(props, "Description", "ProjectDescription", default=name))
    project_type = str(first_value(props, "ProjectType", default="Other"))
    tip_sum = money_to_millions(props.get("TIPSum"))
    project_cost = money_to_millions(props.get("ProjectCost"))

    return {
        "id": project_number,
        "name": name,
        "highway": route_from_project(name),
        "county": "Marion",
        "district": "Ocala Marion TPO",
        "sponsor": "Ocala Marion TPO / FDOT District 5",
        "category": infer_category(project_type),
        "phase": infer_phase(props),
        "funding": "FY 2026-2030 TIP",
        "fiscalYear": infer_phase(props),
        "cost": project_cost or tip_sum,
        "tipFunding": tip_sum,
        "status": "Programmed",
        "sourceUrl": WEB_APP_URL,
        "description": description,
        "geometryType": geometry_type,
        "geometry": geometry,
        "properties": {
            "project_type": project_type,
            "length_miles": first_value(props, "Miles", "Length"),
            "prior_tip_funding": props.get("PriorTIPFunding"),
            "fy2026": props.get("FY2026"),
            "fy2027": props.get("FY2027"),
            "fy2028": props.get("FY2028"),
            "fy2029": props.get("FY2029") or props.get("Field8"),
            "fy2030": props.get("FY2030"),
            "future_funding": props.get("FutureFunding"),
            "source_geometry_type": source_geometry_type,
        },
    }


def load_features(path: pathlib.Path, source_geometry_type: str) -> list[dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [
        project
        for feature in raw.get("features", [])
        if (project := normalize_feature(feature, source_geometry_type))
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description="Normalize Ocala Marion TPO TIP data.")
    parser.add_argument("--lines", default="../data/raw/ocala_tip_lines_raw.geojson")
    parser.add_argument("--points", default="../data/raw/ocala_tip_points_raw.geojson")
    parser.add_argument("--output", default="../data/projects.geojson")
    parser.add_argument("--metadata", default="../data/metadata.json")
    args = parser.parse_args()

    script_dir = pathlib.Path(__file__).resolve().parent
    paths = {}
    for key in ["lines", "points", "output", "metadata"]:
        path = pathlib.Path(getattr(args, key))
        paths[key] = path if path.is_absolute() else script_dir / path

    projects = load_features(paths["lines"], "line") + load_features(paths["points"], "point")
    projects.sort(key=lambda item: (item["category"], item["name"]))

    collection = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": dashboard_geometry_to_geojson(project["geometryType"], project["geometry"]),
                "properties": project,
            }
            for project in projects
        ],
    }
    paths["output"].parent.mkdir(parents=True, exist_ok=True)
    paths["output"].write_text(json.dumps(collection, indent=2), encoding="utf-8")

    metadata = {
        "name": "Ocala Marion TPO TIP Tracker Demo",
        "source": "Ocala Marion TPO FY 2026-2030 TIP Web Map",
        "source_url": WEB_APP_URL,
        "tip_url": TPO_TIP_URL,
        "normalized_at": datetime.now(timezone.utc).isoformat(),
        "record_count": len(projects),
        "line_project_count": sum(1 for project in projects if project["geometryType"] == "LineString"),
        "point_project_count": sum(1 for project in projects if project["geometryType"] == "Point"),
        "notes": "Public Ocala Marion TPO TIP project layers normalized into Parker & Vale's dashboard schema. Review before using for official public reporting.",
    }
    paths["metadata"].write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(f"Wrote {len(projects)} normalized Ocala TIP projects to {paths['output']}")
    print(f"Wrote metadata to {paths['metadata']}")


if __name__ == "__main__":
    main()
