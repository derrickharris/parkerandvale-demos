#!/usr/bin/env python3
"""Export a geographic fieldwork checklist CSV for driving routes."""

from __future__ import annotations

import argparse
import csv
import json
import math
import pathlib
from collections import defaultdict
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parent.parent
DEFAULT_INPUT = ROOT / "data" / "churches.geojson"
DEFAULT_OUTPUT = ROOT / "data" / "fieldwork_checklist.csv"

# ~2.5 km grid cells for initial grouping
CELL_DEG = 0.022
TARGET_STOPS_PER_DAY = 12


def haversine_m(a: dict[str, Any], b: dict[str, Any]) -> float:
    radius = 6_371_000
    lat1, lat2 = math.radians(a["lat"]), math.radians(b["lat"])
    dlat = math.radians(b["lat"] - a["lat"])
    dlon = math.radians(b["lon"] - a["lon"])
    x = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(x))


def cell_key(church: dict[str, Any]) -> tuple[int, int]:
    return (round(church["lat"] / CELL_DEG), round(church["lon"] / CELL_DEG))


def area_label(cluster: list[dict[str, Any]]) -> str:
    lat = sum(c["lat"] for c in cluster) / len(cluster)
    lon = sum(c["lon"] for c in cluster) / len(cluster)
    if abs(lat - 34.505) < 0.01 and abs(lon + 93.055) < 0.02:
        return "Central Hot Springs"
    ns = "North" if lat > 34.505 else "South"
    ew = "East" if lon > -93.055 else "West"
    return f"{ns} {ew}"


def order_cluster(cluster: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if len(cluster) <= 1:
        return cluster
    remaining = cluster[:]
    start = min(remaining, key=lambda c: (c["lat"], c["lon"]))
    ordered = [start]
    remaining.remove(start)
    while remaining:
        last = ordered[-1]
        nxt = min(remaining, key=lambda c: haversine_m(last, c))
        ordered.append(nxt)
        remaining.remove(nxt)
    return ordered


def merge_drive_days(clusters: list[list[dict[str, Any]]], target: int) -> list[list[dict[str, Any]]]:
    """Merge small adjacent grid clusters into practical drive days."""
    if not clusters:
        return []

    def centroid(cluster: list[dict[str, Any]]) -> tuple[float, float]:
        return (
            sum(c["lat"] for c in cluster) / len(cluster),
            sum(c["lon"] for c in cluster) / len(cluster),
        )

    days: list[list[dict[str, Any]]] = []
    for cluster in sorted(clusters, key=lambda c: (-centroid(c)[0], centroid(c)[1])):
        placed = False
        for day in days:
            if len(day) + len(cluster) <= target:
                day_lat, day_lon = centroid(day)
                cl_lat, cl_lon = centroid(cluster)
                if haversine_m({"lat": day_lat, "lon": day_lon}, {"lat": cl_lat, "lon": cl_lon}) < 4500:
                    day.extend(cluster)
                    placed = True
                    break
        if not placed:
            days.append(cluster[:])

    # Sweep any tiny trailing day into nearest neighbor day
    if len(days) > 1 and len(days[-1]) < 4:
        tail = days.pop()
        best_idx = min(
            range(len(days)),
            key=lambda i: haversine_m(
                {"lat": sum(c["lat"] for c in days[i]) / len(days[i]),
                 "lon": sum(c["lon"] for c in days[i]) / len(days[i])},
                {"lat": sum(c["lat"] for c in tail) / len(tail),
                 "lon": sum(c["lon"] for c in tail) / len(tail)},
            ),
        )
        days[best_idx].extend(tail)

    return days


def load_churches(path: pathlib.Path) -> list[dict[str, Any]]:
    features = json.loads(path.read_text(encoding="utf-8"))["features"]
    churches: list[dict[str, Any]] = []
    for feature in features:
        props = feature["properties"]
        lon, lat = feature["geometry"]["coordinates"]
        churches.append({
            "church_id": props["church_id"],
            "name": props["name"],
            "address": props.get("address") or "",
            "denomination": props.get("denomination") or "",
            "shot_status": props.get("shot_status") or "pending",
            "confidence": props.get("confidence") or "",
            "lat": lat,
            "lon": lon,
        })
    return churches


def build_rows(churches: list[dict[str, Any]]) -> list[dict[str, str]]:
    grid: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
    for church in churches:
        grid[cell_key(church)].append(church)

    micro_clusters = [order_cluster(group) for group in grid.values()]
    drive_days = merge_drive_days(micro_clusters, TARGET_STOPS_PER_DAY)

    rows: list[dict[str, str]] = []
    stop = 0
    for day_idx, day in enumerate(drive_days, start=1):
        ordered_day = order_cluster(day)
        label = area_label(ordered_day)
        group_name = f"Route {day_idx:02d} — {label} ({len(ordered_day)} stops)"
        for group_stop, church in enumerate(ordered_day, start=1):
            stop += 1
            filmed = church["shot_status"] == "filmed"
            rows.append({
                "stop": str(stop),
                "route": group_name,
                "route_stop": str(group_stop),
                "filmed": "yes" if filmed else "",
                "church_id": church["church_id"],
                "name": church["name"],
                "address": church["address"],
                "denomination": church["denomination"],
                "shot_status": church["shot_status"],
                "confidence": church["confidence"],
                "lat": f"{church['lat']:.6f}",
                "lon": f"{church['lon']:.6f}",
                "maps_link": (
                    f"https://www.google.com/maps/dir/?api=1&destination={church['lat']},{church['lon']}"
                ),
                "visited": "",
                "notes": "",
            })
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Export fieldwork driving checklist CSV.")
    parser.add_argument("--input", type=pathlib.Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=pathlib.Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    churches = load_churches(args.input)
    rows = build_rows(churches)
    fieldnames = [
        "stop", "route", "route_stop", "filmed", "church_id", "name", "address",
        "denomination", "shot_status", "confidence", "lat", "lon", "maps_link",
        "visited", "notes",
    ]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    routes = {row["route"] for row in rows}
    filmed = sum(1 for row in rows if row["filmed"] == "yes")
    print(f"Wrote {len(rows)} churches to {args.output}")
    print(f"Suggested routes: {len(routes)} (~{TARGET_STOPS_PER_DAY} stops max each)")
    print(f"Already filmed: {filmed} | Remaining: {len(rows) - filmed}")
    for route in sorted(routes, key=lambda r: int(r.split()[1])):
        print(f"  {route}")


if __name__ == "__main__":
    main()
