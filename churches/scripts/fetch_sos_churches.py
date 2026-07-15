#!/usr/bin/env python3
"""Normalize Arkansas Secretary of State nonprofit exports for church cross-reference.

Arkansas SOS does not publish a free public API. Typical workflow:
1. Purchase or export a nonprofit list from https://www.sos.arkansas.gov/business-commercial-services-bcs/
2. Save as CSV at ../data/raw/sos_nonprofits_export.csv
3. Run this script to filter church-like Hot Springs organizations

The output is optional input for normalize_churches.py.
"""

from __future__ import annotations

import argparse
import csv
import json
import pathlib
import re
from datetime import datetime, timezone
from typing import Any

CHURCH_PATTERN = re.compile(
    r"\b(CHURCH|CHAPEL|PARISH|MINISTRY|CATHEDRAL|TABERNACLE|"
    r"BAPTIST|METHODIST|CATHOLIC|PENTECOSTAL|LUTHERAN|PRESBYTERIAN|"
    r"ASSEMBLY OF GOD|CHURCH OF GOD|CHURCH OF CHRIST|EPISCOPAL|"
    r"CHRISTIAN|CONGREGATION|DIOCESE|WORSHIP)\b",
    re.IGNORECASE,
)

NAME_FIELDS = ("name", "entity_name", "corporation_name", "organization_name", "company_name")
CITY_FIELDS = ("city", "principal_city", "mailing_city", "registered_city")
ADDRESS_FIELDS = ("address", "principal_address", "mailing_address", "street_address")
DATE_FIELDS = ("incorporation_date", "date_of_incorporation", "filing_date", "formation_date")
FILING_FIELDS = ("filing_number", "filing_no", "entity_number", "corp_number")


def first_value(row: dict[str, str], *fields: str) -> str:
    for field in fields:
        for key, value in row.items():
            if key.lower() == field and (value or "").strip():
                return value.strip()
    return ""


def normalize_row(row: dict[str, str]) -> dict[str, Any] | None:
    name = first_value(row, *NAME_FIELDS)
    if not name or not CHURCH_PATTERN.search(name):
        return None

    city = first_value(row, *CITY_FIELDS)
    if city and "hot spring" not in city.lower():
        return None

    return {
        "name": name,
        "filing_number": first_value(row, *FILING_FIELDS),
        "address": first_value(row, *ADDRESS_FIELDS),
        "city": city or "Hot Springs",
        "incorporation_date": first_value(row, *DATE_FIELDS),
        "status": first_value(row, "status", "entity_status"),
        "lat": None,
        "lon": None,
        "notes": "Geocode this address before normalize will place it on the map.",
    }


def load_csv(path: pathlib.Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def main() -> None:
    parser = argparse.ArgumentParser(description="Filter SOS nonprofit export for church organizations.")
    parser.add_argument("--input", default="../data/raw/sos_nonprofits_export.csv")
    parser.add_argument("--output", default="../data/raw/sos_churches.json")
    args = parser.parse_args()

    script_dir = pathlib.Path(__file__).resolve().parent
    input_path = script_dir / args.input
    output_path = script_dir / args.output
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if not input_path.exists():
        payload = {
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "source": "Arkansas Secretary of State nonprofit export (optional)",
            "source_url": "https://www.sos.arkansas.gov/business-commercial-services-bcs/",
            "organization_count": 0,
            "organizations": [],
            "notes": (
                "No SOS export found. Drop a CSV at data/raw/sos_nonprofits_export.csv "
                "from the Arkansas SOS bulk/custom list service, then re-run this script."
            ),
        }
        output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"No SOS export at {input_path}")
        print(f"Wrote placeholder {output_path}")
        return

    organizations = []
    for row in load_csv(input_path):
        parsed = normalize_row(row)
        if parsed:
            organizations.append(parsed)

    payload = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "source": "Arkansas Secretary of State nonprofit export",
        "source_url": "https://www.sos.arkansas.gov/business-commercial-services-bcs/",
        "organization_count": len(organizations),
        "organizations": organizations,
        "notes": (
            "SOS records are legal incorporations, not proof of an active congregation or worship site. "
            "Geocode addresses (or add lat/lon in enrichment.csv) before they appear on the map."
        ),
    }
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Wrote {len(organizations)} SOS church-like organizations to {output_path}")


if __name__ == "__main__":
    main()
