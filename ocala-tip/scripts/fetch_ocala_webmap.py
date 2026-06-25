#!/usr/bin/env python3
"""Fetch Ocala Marion TPO FY 2026-2030 TIP project layers.

The TPO web map exposes separate line and point project layers. This script
keeps those raw public GeoJSON responses local so only normalized dashboard
data is deployed.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import urllib.parse
import urllib.request
from datetime import datetime, timezone


WEB_APP_URL = "https://marioncountyfl.maps.arcgis.com/apps/webappviewer/index.html?id=a1591413f8aa4cc7b2d78110c9b4e1a3"
WEB_MAP_ITEM = "aaf1935dee5d45468ea008d86bafc0df"
LINE_LAYER_URL = "https://services1.arcgis.com/oMGpBoZpy1Db2sAl/arcgis/rest/services/FY26_to30Anend2/FeatureServer/18/query"
POINT_LAYER_URL = "https://services1.arcgis.com/oMGpBoZpy1Db2sAl/arcgis/rest/services/FY_26_30_PointsTP2Amdn/FeatureServer/9/query"


def fetch_layer(url: str, limit: int) -> dict:
    params = {
        "f": "geojson",
        "where": "1=1",
        "outFields": "*",
        "returnGeometry": "true",
        "outSR": "4326",
        "resultRecordCount": str(limit),
    }
    request_url = f"{url}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(request_url, headers={"User-Agent": "ParkerValeOcalaTIPDemo/1.0"})
    with urllib.request.urlopen(request, timeout=45) as response:
        return json.load(response)


def write_json(path: pathlib.Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch Ocala Marion TPO TIP project layers.")
    parser.add_argument("--limit", type=int, default=2000)
    parser.add_argument("--output-dir", default="../data/raw")
    args = parser.parse_args()

    output_dir = pathlib.Path(args.output_dir)
    if not output_dir.is_absolute():
        output_dir = pathlib.Path(__file__).resolve().parent / output_dir

    fetched_at = datetime.now(timezone.utc).isoformat()
    line_data = fetch_layer(LINE_LAYER_URL, args.limit)
    point_data = fetch_layer(POINT_LAYER_URL, args.limit)

    for data, geometry_type, source_url in [
        (line_data, "line", LINE_LAYER_URL),
        (point_data, "point", POINT_LAYER_URL),
    ]:
        data.setdefault("properties", {})
        data["properties"].update(
            {
                "source": "Ocala Marion TPO FY 2026-2030 TIP Web Map",
                "source_url": source_url,
                "web_app_url": WEB_APP_URL,
                "web_map_item": WEB_MAP_ITEM,
                "geometry_type": geometry_type,
                "fetched_at": fetched_at,
                "record_count": len(data.get("features", [])),
            }
        )

    write_json(output_dir / "ocala_tip_lines_raw.geojson", line_data)
    write_json(output_dir / "ocala_tip_points_raw.geojson", point_data)
    print(f"Wrote {len(line_data.get('features', []))} line projects")
    print(f"Wrote {len(point_data.get('features', []))} point projects")
    print(f"Output directory: {output_dir}")


if __name__ == "__main__":
    main()
