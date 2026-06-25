#!/usr/bin/env python3
"""Build Garland County crash GeoJSON from public NHTSA FARS downloads."""

from __future__ import annotations

import csv
import io
import json
import urllib.request
import zipfile
from collections import defaultdict
from pathlib import Path


YEARS = range(2019, 2024)
STATE_CODE = "5"  # Arkansas
COUNTY_CODE = "51"  # Garland County
BASE_URL = "https://static.nhtsa.gov/nhtsa/downloads/FARS/{year}/National/FARS{year}NationalCSV.zip"

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"
OUT_PATH = ROOT / "data" / "fars_garland_county_2019_2023.geojson"


def int_value(value: str | None, default: int = 0) -> int:
    try:
        return int(value or default)
    except ValueError:
        return default


def float_value(value: str | None) -> float | None:
    try:
        parsed = float(value or "")
    except ValueError:
        return None
    # FARS uses 77/88/99-style sentinel coordinates for missing or unknown locations.
    if parsed in {77.7777, 88.8888, 99.9999, 777.7777, 888.8888, 999.9999}:
        return None
    return parsed


def clean_label(value: str | None) -> str:
    if not value:
        return ""
    return " ".join(value.replace("\xa0", " ").split())


def download_archive(year: int) -> Path:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    archive_path = RAW_DIR / f"FARS{year}NationalCSV.zip"
    if archive_path.exists():
        return archive_path

    url = BASE_URL.format(year=year)
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=120) as response:
        archive_path.write_bytes(response.read())
    return archive_path


def read_csv_from_zip(archive_path: Path, filename: str) -> list[dict[str, str]]:
    with zipfile.ZipFile(archive_path) as archive:
        matches = [name for name in archive.namelist() if name.lower().endswith(f"/{filename}")]
        if not matches:
            matches = [name for name in archive.namelist() if name.lower().endswith(filename)]
        if not matches:
            raise FileNotFoundError(f"{filename} not found in {archive_path.name}")

        with archive.open(matches[0]) as csv_file:
            text_file = io.TextIOWrapper(csv_file, encoding="utf-8-sig", errors="replace")
            return list(csv.DictReader(text_file))


def is_garland(row: dict[str, str]) -> bool:
    return row.get("STATE") == STATE_CODE and row.get("COUNTY") == COUNTY_CODE


def format_time(hour: int, minute: int) -> str:
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        return "Unknown"
    suffix = "AM" if hour < 12 else "PM"
    display_hour = hour % 12 or 12
    return f"{display_hour}:{minute:02d} {suffix}"


def is_dark(light: str) -> bool:
    return "dark" in light.lower()


def is_wet(weather: str) -> bool:
    lowered = weather.lower()
    return any(term in lowered for term in ("rain", "sleet", "snow", "fog", "smog", "smoke"))


def is_intersection(row: dict[str, str]) -> bool:
    reljct = clean_label(row.get("RELJCT1NAME")).lower()
    reljct2 = clean_label(row.get("RELJCT2NAME")).lower()
    typ_int = clean_label(row.get("TYP_INTNAME")).lower()
    return (
        "yes" in reljct
        or "intersection" in reljct2
        or ("intersection" in typ_int and "not an intersection" not in typ_int)
    )


def collect_person_context(rows: list[dict[str, str]]) -> dict[str, dict[str, int | bool]]:
    context: dict[str, dict[str, int | bool]] = defaultdict(
        lambda: {"ped_bike": False, "serious_injuries": 0}
    )

    for row in rows:
        if not is_garland(row):
            continue

        case_id = row.get("ST_CASE", "")
        person_type = clean_label(row.get("PER_TYPNAME")).lower()
        injury_name = clean_label(row.get("INJ_SEVNAME")).lower()
        injury_code = row.get("INJ_SEV")

        if any(term in person_type for term in ("pedestrian", "bicyclist", "pedalcyclist", "cyclist")):
            context[case_id]["ped_bike"] = True

        if injury_code == "3" or "suspected serious" in injury_name or "incapacitating" in injury_name:
            context[case_id]["serious_injuries"] = int(context[case_id]["serious_injuries"]) + 1

    return context


def build_feature(row: dict[str, str], person_context: dict[str, dict[str, int | bool]]) -> dict | None:
    lat = float_value(row.get("LATITUDE"))
    lon = float_value(row.get("LONGITUD"))
    if lat is None or lon is None:
        return None

    case_id = row.get("ST_CASE", "")
    year = int_value(row.get("YEAR"))
    month = int_value(row.get("MONTH"))
    day = int_value(row.get("DAY"))
    hour = int_value(row.get("HOUR"), -1)
    minute = int_value(row.get("MINUTE"), -1)
    light = clean_label(row.get("LGT_CONDNAME"))
    weather = clean_label(row.get("WEATHERNAME"))
    route = clean_label(row.get("TWAY_ID")) or clean_label(row.get("ROUTENAME")) or "Unknown roadway"
    city = clean_label(row.get("CITYNAME"))
    context = person_context.get(case_id, {"ped_bike": False, "serious_injuries": 0})

    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
        "properties": {
            "source": "NHTSA FARS",
            "case_id": case_id,
            "date": f"{year:04d}-{month:02d}-{day:02d}",
            "time": format_time(hour, minute),
            "street": route,
            "city": city,
            "num_fatal": int_value(row.get("FATALS")),
            "num_inj": int(context["serious_injuries"]),
            "is_ped": bool(context["ped_bike"]) or int_value(row.get("PEDS")) > 0,
            "light": light,
            "weather": weather,
            "alcohol": False,
            "intersection": is_intersection(row),
            "year": year,
            "county": "Garland County",
            "state": "Arkansas",
            "route_type": clean_label(row.get("ROUTENAME")),
            "functional_system": clean_label(row.get("FUNC_SYSNAME")),
            "first_harmful_event": clean_label(row.get("HARM_EVNAME")),
            "manner_of_collision": clean_label(row.get("MAN_COLLNAME")),
            "relation_to_junction": clean_label(row.get("RELJCT2NAME")),
            "rural_urban": clean_label(row.get("RUR_URBNAME")),
            "dark": is_dark(light),
            "wet": is_wet(weather),
        },
    }


def main() -> None:
    features: list[dict] = []

    for year in YEARS:
        archive_path = download_archive(year)
        accidents = read_csv_from_zip(archive_path, "accident.csv")
        persons = read_csv_from_zip(archive_path, "person.csv")
        person_context = collect_person_context(persons)

        for row in accidents:
            if not is_garland(row):
                continue
            feature = build_feature(row, person_context)
            if feature:
                features.append(feature)

    features.sort(key=lambda feature: (feature["properties"]["date"], feature["properties"]["case_id"]))
    geojson = {
        "type": "FeatureCollection",
        "metadata": {
            "title": "Garland County, Arkansas fatal motor vehicle crashes",
            "source": "NHTSA Fatality Analysis Reporting System (FARS)",
            "source_url": "https://www.nhtsa.gov/research-data/fatality-analysis-reporting-system-fars",
            "years": [min(YEARS), max(YEARS)],
            "state_code": STATE_CODE,
            "county_code": COUNTY_CODE,
            "generated_by": "safety/scripts/fetch_fars_garland.py",
            "notes": [
                "FARS is a census of fatal motor vehicle traffic crashes.",
                "Suspected serious injury counts here are only injuries that occurred within fatal-crash records.",
                "Alcohol/drug involvement is not inferred by this normalizer.",
            ],
        },
        "features": features,
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(geojson, indent=2), encoding="utf-8")
    print(f"Wrote {len(features)} crash records to {OUT_PATH}")


if __name__ == "__main__":
    main()
