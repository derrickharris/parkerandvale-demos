#!/usr/bin/env python3
"""Fetch FDOT Work Program records for Marion County.

This optional reference pull is useful when validating the Ocala Marion TPO TIP
against FDOT's current five-year work program. The dashboard itself is built
from normalized public-safe data, not raw source dumps.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import urllib.parse
import urllib.request
from datetime import datetime, timezone


BASE_LAYER_URL = "https://gis.fdot.gov/arcgis/rest/services/Work_Program_Current/FeatureServer"
DEFAULT_LAYER_IDS = [2, 13, 15, 17, 20]


def fetch_layer(layer_id: int, limit: int) -> dict:
    url = f"{BASE_LAYER_URL}/{layer_id}/query"
    params = {
        "f": "geojson",
        "where": "CONTYNAM = 'MARION'",
        "outFields": "*",
        "returnGeometry": "true",
        "outSR": "4326",
        "resultRecordCount": str(limit),
    }
    request_url = f"{url}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(request_url, headers={"User-Agent": "ParkerValeOcalaTIPDemo/1.0"})
    with urllib.request.urlopen(request, timeout=45) as response:
        return json.load(response)


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch FDOT Work Program records for Marion County.")
    parser.add_argument("--layers", default=",".join(str(i) for i in DEFAULT_LAYER_IDS))
    parser.add_argument("--limit", type=int, default=2000)
    parser.add_argument("--output", default="../data/raw/fdot_marion_work_program_raw.geojson")
    args = parser.parse_args()

    layer_ids = [int(value.strip()) for value in args.layers.split(",") if value.strip()]
    fetched_at = datetime.now(timezone.utc).isoformat()
    features = []

    for layer_id in layer_ids:
        data = fetch_layer(layer_id, args.limit)
        for feature in data.get("features", []):
            feature.setdefault("properties", {})
            feature["properties"]["source_layer_id"] = layer_id
            features.append(feature)

    output = pathlib.Path(args.output)
    if not output.is_absolute():
        output = pathlib.Path(__file__).resolve().parent / output
    output.parent.mkdir(parents=True, exist_ok=True)
    collection = {
        "type": "FeatureCollection",
        "features": features,
        "properties": {
            "source": "FDOT Work Program Current FeatureServer",
            "source_url": BASE_LAYER_URL,
            "where": "CONTYNAM = 'MARION'",
            "layers": layer_ids,
            "fetched_at": fetched_at,
            "record_count": len(features),
        },
    }
    output.write_text(json.dumps(collection, indent=2), encoding="utf-8")
    print(f"Wrote {len(features)} FDOT Work Program records to {output}")


if __name__ == "__main__":
    main()
