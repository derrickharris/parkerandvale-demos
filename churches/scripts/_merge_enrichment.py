#!/usr/bin/env python3
"""One-off merge of dashboard filmed export into enrichment.csv."""

from __future__ import annotations

import csv
import pathlib

BASE = pathlib.Path(__file__).resolve().parent.parent / "data" / "raw" / "enrichment.csv"
INCOMING = pathlib.Path("/Users/derrickharris/Downloads/enrichment_filmed_updates.csv")

FIELDNAMES = [
    "church_id", "osm_id", "assessor_objectid", "name", "denomination", "denomination_raw",
    "year_founded", "address", "lat", "lon", "shot_status", "photo_url", "notes",
]


def keys(row: dict[str, str]) -> set[tuple[str, str]]:
    out: set[tuple[str, str]] = set()
    if (row.get("osm_id") or "").strip():
        out.add(("osm", row["osm_id"].strip()))
    if (row.get("assessor_objectid") or "").strip():
        out.add(("assessor", row["assessor_objectid"].strip()))
    return out


def load(path: pathlib.Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def main() -> None:
    existing = load(BASE)
    updates = load(INCOMING)

    by_key: dict[tuple[str, str], int] = {}
    for idx, row in enumerate(existing):
        for key in keys(row):
            by_key[key] = idx

    merged = [dict(row) for row in existing]
    added = 0
    updated = 0

    for row in updates:
        if (row.get("shot_status") or "").strip().lower() != "filmed":
            continue
        match_idxs = {by_key[key] for key in keys(row) if key in by_key}
        if match_idxs:
            for idx in match_idxs:
                target = merged[idx]
                target["shot_status"] = "filmed"
                if not target.get("osm_id") and row.get("osm_id"):
                    target["osm_id"] = row["osm_id"]
                if not target.get("assessor_objectid") and row.get("assessor_objectid"):
                    target["assessor_objectid"] = row["assessor_objectid"]
                if not target.get("photo_url"):
                    note = (target.get("notes") or "").strip()
                    marked = (row.get("notes") or "Marked filmed in dashboard").strip()
                    if marked and marked not in note:
                        target["notes"] = f"{note}; {marked}".strip("; ") if note else marked
                updated += 1
        else:
            new_row = {field: (row.get(field) or "").strip() for field in FIELDNAMES}
            if not new_row["notes"]:
                new_row["notes"] = "Marked filmed in dashboard"
            merged.append(new_row)
            for key in keys(new_row):
                by_key[key] = len(merged) - 1
            added += 1

    with BASE.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        for row in merged:
            writer.writerow({field: row.get(field, "") for field in FIELDNAMES})

    print(f"existing={len(existing)} updates={len(updates)} added={added} updated={updated} final={len(merged)}")
    print(f"wrote {BASE}")


if __name__ == "__main__":
    main()
