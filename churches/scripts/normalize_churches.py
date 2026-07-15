#!/usr/bin/env python3
"""Normalize OSM + assessor church records into dashboard GeoJSON."""

from __future__ import annotations

import argparse
import csv
import json
import math
import pathlib
import re
from datetime import datetime, timezone
from typing import Any

POPULATION = 37930
POPULATION_SOURCE = "U.S. Census 2020 — Hot Springs city"
CITY_AREA_SQ_MI = 35.14  # U.S. Census land area, Hot Springs city
CITY_AREA_SOURCE = "U.S. Census — Hot Springs city land area"

CITY_BBOX = {
    "min_lat": 34.44,
    "max_lat": 34.57,
    "min_lon": -93.13,
    "max_lon": -92.97,
}

CAMPUS_DISTANCE_M = 120.0
CAMPUS_NETWORK_M = 400.0
# Same church may legitimately worship at multiple nearby street addresses.
MULTI_SITE_IDENTITY_KEYS = {"roanoke baptist", "st john catholic"}
CAMPUS_NAME_STOPWORDS = {
    "inc", "incorporated", "church", "churches", "ch", "chr", "of", "the", "in",
    "hot", "springs", "arkansas", "ar", "corp", "corporation", "tr", "assoc",
    "association", "congregation", "ministry", "ministries",
}

DENOMINATION_MAP = {
    "baptist": "Baptist",
    "southern_baptist": "Baptist",
    "southern baptist": "Baptist",
    "independent_baptist": "Baptist",
    "national_baptist": "Baptist",
    "american_baptist": "Baptist",
    "methodist": "Methodist",
    "united_methodist": "Methodist",
    "united methodist": "Methodist",
    "african_methodist_episcopal": "Methodist",
    "catholic": "Catholic",
    "roman_catholic": "Catholic",
    "orthodox": "Orthodox",
    "greek_orthodox": "Orthodox",
    "pentecostal": "Pentecostal",
    "assemblies_of_god": "Pentecostal",
    "church_of_god": "Pentecostal",
    "church_of_god_in_christ": "Pentecostal",
    "lutheran": "Lutheran",
    "evangelical_lutheran": "Lutheran",
    "presbyterian": "Presbyterian",
    "pcusa": "Presbyterian",
    "episcopal": "Episcopal",
    "anglican": "Anglican",
    "latter_day_saints": "Latter-day Saints",
    "latter-day saints": "Latter-day Saints",
    "lds": "Latter-day Saints",
    "anglican": "Episcopal",
    "church_of_christ": "Church of Christ",
    "nondenominational": "Nondenominational",
    "non-denominational": "Nondenominational",
    "interdenominational": "Nondenominational",
    "christian": "Christian",
    "protestant": "Protestant",
    "adventist": "Adventist",
    "seventh_day_adventist": "Adventist",
    "jehovahs_witnesses": "Other",
    "mormon": "Other",
    "unitarian": "Other",
}

NAME_DENOMINATION_HINTS = [
    ("baptist", "Baptist"),
    ("methodist", "Methodist"),
    ("catholic", "Catholic"),
    ("pentecostal", "Pentecostal"),
    ("lutheran", "Lutheran"),
    ("presbyterian", "Presbyterian"),
    ("anglican", "Anglican"),
    ("latter-day", "Latter-day Saints"),
    ("latter day", "Latter-day Saints"),
    ("episcopal", "Episcopal"),
    ("church of christ", "Church of Christ"),
    ("assembly of god", "Pentecostal"),
    ("church of god", "Pentecostal"),
    ("adventist", "Adventist"),
    ("orthodox", "Orthodox"),
    ("nondenominational", "Nondenominational"),
    ("non-denominational", "Nondenominational"),
]


def in_city_bbox(lat: float | None, lon: float | None) -> bool:
    if lat is None or lon is None:
        return False
    return (
        CITY_BBOX["min_lat"] <= lat <= CITY_BBOX["max_lat"]
        and CITY_BBOX["min_lon"] <= lon <= CITY_BBOX["max_lon"]
    )


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(a))


def normalize_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).strip()


def campus_name_tokens(name: str) -> set[str]:
    tokens = {
        token for token in normalize_key(name).split()
        if len(token) > 1 and token not in CAMPUS_NAME_STOPWORDS
    }
    return tokens


def names_similar(name_a: str, name_b: str) -> bool:
    key_a = normalize_key(name_a)
    key_b = normalize_key(name_b)
    if not key_a or not key_b:
        return False
    if key_a == key_b or key_a in key_b or key_b in key_a:
        return True

    tokens_a = campus_name_tokens(name_a)
    tokens_b = campus_name_tokens(name_b)
    if not tokens_a or not tokens_b:
        return False
    overlap = len(tokens_a & tokens_b)
    union = len(tokens_a | tokens_b)
    if overlap >= 2 and overlap / union >= 0.5:
        return True
    return overlap / min(len(tokens_a), len(tokens_b)) >= 0.75


def pick_better_record(current: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    return candidate if tag_score(candidate) > tag_score(current) else current


def collapse_campus_clusters(
    records: list[dict[str, Any]],
    distance_m: float = CAMPUS_DISTANCE_M,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Merge same-name, nearby parcels into one campus pin. Returns (collapsed, merged_away)."""
    clusters: list[dict[str, Any]] = []
    merged_away: list[dict[str, Any]] = []

    for record in sorted(records, key=tag_score, reverse=True):
        matched_cluster = None
        for cluster in clusters:
            if not names_similar(record.get("name", ""), cluster["name"]):
                continue
            if haversine_m(record["lat"], record["lon"], cluster["lat"], cluster["lon"]) <= distance_m:
                matched_cluster = cluster
                break

        if matched_cluster is None:
            clusters.append(dict(record))
            continue

        merged_away.append(record)
        matched_cluster["name"] = pick_better_record(matched_cluster, record)["name"]
        if len(record.get("address", "")) > len(matched_cluster.get("address", "")):
            matched_cluster["address"] = record["address"]
        count = matched_cluster.get("parcel_count", 1) + 1
        matched_cluster["parcel_count"] = count
        matched_cluster["lat"] = (
            (matched_cluster["lat"] * (count - 1)) + record["lat"]
        ) / count
        matched_cluster["lon"] = (
            (matched_cluster["lon"] * (count - 1)) + record["lon"]
        ) / count

    return clusters, merged_away


def campus_identity_key(name: str) -> str:
    lowered = normalize_key(name)
    if "oaklawn" in lowered and "methodist" in lowered:
        return "oaklawn methodist"
    if "oaklawn" in lowered and "baptist" in lowered and "missionary" not in lowered:
        return "oaklawn baptist"
    if "gospel" in lowered and "light" in lowered:
        return "gospel light"
    if "first" in lowered and "baptist" in lowered:
        return "first baptist"
    if "new" in lowered and "life" in lowered:
        return "new life"
    if "roanoke" in lowered and "baptist" in lowered and "missionary" not in lowered:
        return "roanoke baptist"
    if ("st john" in lowered or "saint john" in lowered) and "catholic" in lowered:
        return "st john catholic"
    if ("st paul" in lowered or "saint paul" in lowered) and ("ame" in lowered or "methodist" in lowered):
        return "st paul ame"
    return " ".join(sorted(campus_name_tokens(name)))


def parse_address_parts(address: str) -> tuple[str | None, str | None]:
    cleaned = normalize_key(address)
    if not cleaned:
        return None, None
    match = re.match(r"^(\d+)\s+(.+)$", cleaned)
    if match:
        return match.group(1), match.group(2)
    return None, cleaned


def absorb_record(target: dict[str, Any], source: dict[str, Any]) -> None:
    target["parcel_count"] = target.get("parcel_count", 1) + source.get("parcel_count", 1)
    if len(source.get("address", "")) > len(target.get("address", "")):
        target["address"] = source["address"]
    if not target.get("website") and source.get("website"):
        target["website"] = source["website"]
    if not target.get("phone") and source.get("phone"):
        target["phone"] = source["phone"]
    if not target.get("osm_id") and source.get("osm_id"):
        target["osm_id"] = source["osm_id"]
        target["osm_type"] = source.get("osm_type")
    if not target.get("assessor_objectid") and source.get("assessor_objectid"):
        target["assessor_objectid"] = source.get("assessor_objectid")
        target["parcelid"] = source.get("parcelid", "")
    target["sources"] = sorted(set(target.get("sources", [])) | set(source.get("sources", [])))


def merge_cluster_records(
    cluster: list[dict[str, Any]],
    identity_key: str | None = None,
) -> list[dict[str, Any]]:
    if len(cluster) == 1:
        return cluster

    by_site: dict[tuple[str, str], dict[str, Any]] = {}
    generic: list[dict[str, Any]] = []

    for record in cluster:
        house, street = parse_address_parts(record.get("address", ""))
        if house and street:
            key = (house, street)
            if key not in by_site or tag_score(record) > tag_score(by_site[key]):
                by_site[key] = dict(record)
        else:
            generic.append(record)

    if by_site:
        sites = list(by_site.values())
        if identity_key in MULTI_SITE_IDENTITY_KEYS:
            # Keep separately addressed/unlabeled parcels as distinct campus pins.
            return sites + generic
        if len(sites) == 1:
            for extra in generic:
                absorb_record(sites[0], extra)
            return sites
        best = max(sites + generic, key=tag_score)
        merged_best = dict(best)
        for other in sites + generic:
            if other is not best:
                absorb_record(merged_best, other)
        return [merged_best]

    best = max(cluster, key=tag_score)
    merged_best = dict(best)
    for other in cluster:
        if other is not best:
            absorb_record(merged_best, other)
    return [merged_best]


def network_cluster_by_identity(
    records: list[dict[str, Any]],
    distance_m: float = CAMPUS_NETWORK_M,
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    unkeyed: list[dict[str, Any]] = []

    for record in records:
        key = campus_identity_key(record.get("name", ""))
        if key:
            grouped.setdefault(key, []).append(record)
        else:
            unkeyed.append(record)

    collapsed: list[dict[str, Any]] = []
    for identity_key, group in grouped.items():
        clusters: list[list[dict[str, Any]]] = []
        for record in sorted(group, key=tag_score, reverse=True):
            placed = False
            for cluster in clusters:
                if any(
                    haversine_m(record["lat"], record["lon"], member["lat"], member["lon"]) <= distance_m
                    for member in cluster
                ):
                    cluster.append(record)
                    placed = True
                    break
            if not placed:
                clusters.append([record])
        for cluster in clusters:
            collapsed.extend(merge_cluster_records(cluster, identity_key))

    return collapsed + unkeyed


def load_overrides(path: pathlib.Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def should_exclude(record: dict[str, Any], rules: list[dict[str, str]]) -> bool:
    name = normalize_key(record.get("name", ""))
    address = normalize_key(record.get("address", ""))
    osm_id = str(record.get("osm_id") or "")
    assessor_id = str(record.get("assessor_objectid") or "")

    for rule in rules:
        if (rule.get("action") or "").strip().lower() != "exclude":
            continue
        rule_osm = (rule.get("osm_id") or "").strip()
        rule_assessor = (rule.get("assessor_objectid") or "").strip()
        rule_name = normalize_key(rule.get("match_name", ""))
        rule_addr = normalize_key(rule.get("match_address", ""))

        # ID-targeted rules must not fall through to fuzzy name matching.
        if rule_osm or rule_assessor:
            if rule_osm and rule_osm == osm_id:
                return True
            if rule_assessor and rule_assessor == assessor_id:
                return True
            continue

        if rule_name and rule_name not in name:
            continue
        if rule_addr and rule_addr not in address:
            continue
        if rule_name or rule_addr:
            return True
    return False


def apply_exclusions(records: list[dict[str, Any]], rules: list[dict[str, str]]) -> list[dict[str, Any]]:
    return [record for record in records if not should_exclude(record, rules)]


def standardize_denomination(raw: str, name: str = "") -> str:
    key = normalize_key(raw).replace(" ", "_")
    if key in DENOMINATION_MAP:
        return DENOMINATION_MAP[key]
    if raw:
        cleaned = raw.replace("_", " ").strip()
        if not cleaned or cleaned.lower() in {"unknown", "none", "n/a"}:
            return "Nondenominational"
        return cleaned.title()

    lowered_name = (name or "").lower()
    for hint, label in NAME_DENOMINATION_HINTS:
        if hint in lowered_name:
            return label
    return "Nondenominational"


def parse_year(value: Any) -> int | None:
    if value in (None, ""):
        return None
    text = str(value)
    match = re.search(r"(18|19|20)\d{2}", text)
    if match:
        year = int(match.group(0))
        if 1800 <= year <= datetime.now().year:
            return year
    return None


def tag_score(record: dict[str, Any]) -> int:
    score = 0
    for key in ("name", "denomination_raw", "address", "website", "phone", "start_date", "wikidata"):
        if record.get(key):
            score += 1
    if record.get("name") != "Unnamed":
        score += 2
    return score


def load_json(path: pathlib.Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def load_enrichment(path: pathlib.Path) -> tuple[dict[str, dict[str, str]], list[dict[str, Any]]]:
    if not path.exists():
        return {}, []

    updates: dict[str, dict[str, str]] = {}
    manual_adds: list[dict[str, Any]] = []
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if not any((row.get(field) or "").strip() for field in row):
                continue

            lat = row.get("lat", "").strip()
            lon = row.get("lon", "").strip()
            church_id = (row.get("church_id") or "").strip()
            osm_id = (row.get("osm_id") or "").strip()
            assessor_objectid = (row.get("assessor_objectid") or "").strip()
            name = (row.get("name") or "").strip()

            if lat and lon and name and not church_id and not osm_id and not assessor_objectid:
                try:
                    lat_f = float(lat)
                    lon_f = float(lon)
                except ValueError:
                    continue
                if not in_city_bbox(lat_f, lon_f):
                    continue
                manual_adds.append({
                    "source_kind": "manual",
                    "osm_id": None,
                    "osm_type": None,
                    "assessor_objectid": None,
                    "parcelid": "",
                    "name": name,
                    "denomination_raw": row.get("denomination_raw", ""),
                    "denomination": row.get("denomination", ""),
                    "address": row.get("address", ""),
                    "addr_city": "Hot Springs",
                    "lat": lat_f,
                    "lon": lon_f,
                    "start_date": "",
                    "website": "",
                    "phone": "",
                    "wikidata": "",
                    "sources": ["manual"],
                    "shot_status": row.get("shot_status", "pending"),
                    "photo_url": row.get("photo_url") or None,
                    "notes": row.get("notes", ""),
                    "year_founded": parse_year(row.get("year_founded")),
                })
                continue

            for key in (church_id, osm_id, assessor_objectid):
                if key:
                    updates[key] = row
    return updates, manual_adds


def dedupe_records(records: list[dict[str, Any]], distance_m: float = 30.0) -> list[dict[str, Any]]:
    kept: list[dict[str, Any]] = []
    for record in sorted(records, key=tag_score, reverse=True):
        name_key = normalize_key(record.get("name", ""))
        duplicate = False
        for existing in kept:
            if haversine_m(record["lat"], record["lon"], existing["lat"], existing["lon"]) > distance_m:
                continue
            existing_name = normalize_key(existing.get("name", ""))
            if name_key and existing_name and (
                name_key == existing_name
                or name_key in existing_name
                or existing_name in name_key
            ):
                duplicate = True
                break
        if not duplicate:
            kept.append(record)
    return kept


def make_osm_records(payload: dict[str, Any]) -> list[dict[str, Any]]:
    records = []
    for item in payload.get("churches", []):
        records.append({
            "source_kind": "osm",
            "osm_id": item.get("osm_id"),
            "osm_type": item.get("osm_type"),
            "assessor_objectid": None,
            "parcelid": "",
            "name": item.get("name", "Unnamed"),
            "denomination_raw": item.get("denomination_raw", ""),
            "address": item.get("address") or " ".join(
                part for part in (item.get("addr_housenumber", ""), item.get("addr_street", "")) if part
            ).strip(),
            "addr_city": item.get("addr_city", ""),
            "lat": item["lat"],
            "lon": item["lon"],
            "start_date": item.get("start_date", ""),
            "website": item.get("website", ""),
            "phone": item.get("phone", ""),
            "wikidata": item.get("wikidata", ""),
            "sources": ["osm"],
        })
    return records


def make_assessor_records(payload: dict[str, Any]) -> list[dict[str, Any]]:
    records = []
    for item in payload.get("candidates", []):
        records.append({
            "source_kind": "assessor",
            "osm_id": None,
            "osm_type": None,
            "assessor_objectid": item.get("assessor_objectid"),
            "parcelid": item.get("parcelid", ""),
            "name": item.get("name", "Unnamed Parcel"),
            "denomination_raw": "",
            "address": item.get("address", ""),
            "addr_city": item.get("adrcity", ""),
            "lat": item["lat"],
            "lon": item["lon"],
            "start_date": "",
            "website": "",
            "phone": "",
            "wikidata": "",
            "sources": ["assessor"],
        })
    return records


def make_sos_records(payload: dict[str, Any]) -> list[dict[str, Any]]:
    records = []
    for item in payload.get("organizations", []):
        lat = item.get("lat")
        lon = item.get("lon")
        if lat is None or lon is None:
            continue
        records.append({
            "source_kind": "sos",
            "osm_id": None,
            "osm_type": None,
            "assessor_objectid": None,
            "parcelid": "",
            "sos_filing_number": item.get("filing_number", ""),
            "name": item.get("name", "Unnamed Organization"),
            "denomination_raw": "",
            "address": item.get("address", ""),
            "addr_city": item.get("city", "Hot Springs"),
            "lat": lat,
            "lon": lon,
            "start_date": item.get("incorporation_date", ""),
            "website": "",
            "phone": "",
            "wikidata": "",
            "sources": ["sos"],
        })
    return records


def merge_sos_records(records: list[dict[str, Any]], sos_records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged = [dict(record) for record in records]
    for sos in sos_records:
        best_idx = None
        best_distance = 80.0
        sos_name = normalize_key(sos.get("name", ""))
        for idx, record in enumerate(merged):
            distance = haversine_m(record["lat"], record["lon"], sos["lat"], sos["lon"])
            if distance > 80:
                continue
            if names_similar(sos.get("name", ""), record.get("name", "")) or distance <= 35:
                if distance < best_distance:
                    best_distance = distance
                    best_idx = idx
        if best_idx is not None:
            target = merged[best_idx]
            target_sources = set(target.get("sources", []))
            target_sources.add("sos")
            target["sources"] = sorted(target_sources)
            if not target.get("year_founded"):
                target["year_founded"] = parse_year(sos.get("start_date"))
            if not target.get("address"):
                target["address"] = sos.get("address", "")
        else:
            merged.append(sos)
    return merged


def merge_records(
    osm_records: list[dict[str, Any]],
    assessor_records: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], set[Any]]:
    merged = [dict(record) for record in osm_records]
    matched_assessor_ids: set[Any] = set()
    review_queue: list[dict[str, Any]] = []

    for assessor in assessor_records:
        best_idx = None
        best_distance = 50.0
        assessor_name = normalize_key(assessor.get("name", ""))
        assessor_address = normalize_key(assessor.get("address", ""))

        for idx, osm in enumerate(merged):
            distance = haversine_m(osm["lat"], osm["lon"], assessor["lat"], assessor["lon"])
            if distance > 50:
                continue
            osm_name = normalize_key(osm.get("name", ""))
            osm_address = normalize_key(osm.get("address", ""))
            name_match = bool(
                assessor_name and osm_name and (
                    assessor_name == osm_name
                    or assessor_name in osm_name
                    or osm_name in assessor_name
                    or names_similar(assessor.get("name", ""), osm.get("name", ""))
                )
            )
            address_match = bool(
                assessor_address and osm_address and (
                    assessor_address == osm_address
                    or assessor_address in osm_address
                    or osm_address in assessor_address
                )
            )
            if name_match or address_match or distance <= 25:
                if distance < best_distance:
                    best_distance = distance
                    best_idx = idx

        if best_idx is not None:
            target = merged[best_idx]
            target_sources = set(target.get("sources", []))
            target_sources.add("assessor")
            target["sources"] = sorted(target_sources)
            target["assessor_objectid"] = assessor.get("assessor_objectid")
            target["parcelid"] = assessor.get("parcelid", "")
            if not target.get("address"):
                target["address"] = assessor.get("address", "")
            matched_assessor_ids.add(assessor.get("assessor_objectid"))
        else:
            review_queue.append(assessor)

    return merged, review_queue, matched_assessor_ids


def apply_enrichment(records: list[dict[str, Any]], enrichment: dict[str, dict[str, str]]) -> None:
    for record in records:
        keys = [
            str(record.get("church_id", "")),
            str(record.get("osm_id", "")),
            str(record.get("assessor_objectid", "")),
        ]
        row = next((enrichment[key] for key in keys if key and key in enrichment), None)
        if not row:
            continue
        for field in ("name", "denomination", "denomination_raw", "address", "notes", "photo_url", "shot_status"):
            if row.get(field):
                record[field] = row[field]
        if row.get("year_founded"):
            record["year_founded"] = parse_year(row["year_founded"])
        if row.get("lat") and row.get("lon"):
            try:
                lat_f = float(row["lat"])
                lon_f = float(row["lon"])
            except ValueError:
                lat_f = lon_f = None
            if lat_f is not None and lon_f is not None and in_city_bbox(lat_f, lon_f):
                record["lat"] = lat_f
                record["lon"] = lon_f


def compute_confidence(record: dict[str, Any]) -> tuple[str, list[str], bool]:
    sources = sorted(set(record.get("sources", [])))
    shot_status = (record.get("shot_status") or "pending").strip().lower()

    if shot_status == "filmed":
        sources = sorted(set(sources) | {"field"})
        return "high", sources, False

    source_count = len(sources)
    if source_count >= 3:
        confidence = "high"
    elif source_count == 2:
        confidence = "medium"
    else:
        confidence = "low"
    return confidence, sources, confidence != "high"


def finalize_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    finalized = []
    for idx, record in enumerate(sorted(records, key=lambda r: normalize_key(r.get("name", ""))), start=1):
        church_id = f"hs-{idx:04d}"
        denomination = record.get("denomination") or standardize_denomination(
            record.get("denomination_raw", ""),
            record.get("name", ""),
        )
        if denomination == "Unknown":
            denomination = "Nondenominational"
        confidence, sources, needs_verification = compute_confidence(record)
        finalized.append({
            "church_id": church_id,
            "osm_id": record.get("osm_id"),
            "osm_type": record.get("osm_type"),
            "assessor_objectid": record.get("assessor_objectid"),
            "parcelid": record.get("parcelid", ""),
            "name": record.get("name", "Unnamed"),
            "denomination": denomination,
            "denomination_raw": record.get("denomination_raw", ""),
            "year_founded": record.get("year_founded") or parse_year(record.get("start_date")),
            "address": record.get("address", ""),
            "addr_city": record.get("addr_city", "Hot Springs"),
            "lat": record["lat"],
            "lon": record["lon"],
            "website": record.get("website", ""),
            "phone": record.get("phone", ""),
            "wikidata": record.get("wikidata", ""),
            "confidence": confidence,
            "sources": sources,
            "needs_verification": needs_verification,
            "parcel_count": record.get("parcel_count", 1),
            "shot_status": record.get("shot_status", "pending"),
            "photo_url": record.get("photo_url") or None,
            "notes": record.get("notes", ""),
        })
    return finalized


def write_review_csv(path: pathlib.Path, review_queue: list[dict[str, Any]]) -> None:
    fieldnames = [
        "assessor_objectid", "parcelid", "name", "address", "adrcity", "lat", "lon",
        "parcel_count", "review_reason",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for item in review_queue:
            writer.writerow({
                "assessor_objectid": item.get("assessor_objectid"),
                "parcelid": item.get("parcelid", ""),
                "name": item.get("name", ""),
                "address": item.get("address", ""),
                "adrcity": item.get("adrcity", item.get("addr_city", "")),
                "lat": item.get("lat"),
                "lon": item.get("lon"),
                "parcel_count": item.get("parcel_count", 1),
                "review_reason": item.get("review_reason", "assessor_only_campus_collapsed"),
            })


def write_geojson(path: pathlib.Path, churches: list[dict[str, Any]]) -> None:
    features = []
    for church in churches:
        props = {k: v for k, v in church.items() if k not in ("lat", "lon")}
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [church["lon"], church["lat"]],
            },
            "properties": props,
        })
    collection = {"type": "FeatureCollection", "features": features}
    path.write_text(json.dumps(collection, indent=2), encoding="utf-8")


def write_embed_js(geojson_path: pathlib.Path, metadata: dict[str, Any], output_path: pathlib.Path) -> None:
    payload = json.loads(geojson_path.read_text(encoding="utf-8"))
    script = (
        "// Auto-generated by normalize_churches.py — enables local file:// viewing\n"
        f"window.CHURCHES_EMBED = {json.dumps(payload)};\n"
        f"window.CHURCH_METADATA_EMBED = {json.dumps(metadata)};\n"
    )
    output_path.write_text(script, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Normalize church sources into dashboard GeoJSON.")
    parser.add_argument("--osm", default="../data/raw/osm_churches.json")
    parser.add_argument("--assessor", default="../data/raw/assessor_candidates.json")
    parser.add_argument("--sos", default="../data/raw/sos_churches.json")
    parser.add_argument("--enrichment", default="../data/raw/enrichment.csv")
    parser.add_argument("--overrides", default="../data/raw/overrides.csv")
    parser.add_argument("--output", default="../data/churches.geojson")
    parser.add_argument("--metadata", default="../data/metadata.json")
    parser.add_argument("--embed-js", default="../data/churches_data.js")
    parser.add_argument("--review-csv", default="../data/raw/assessor_candidates.csv")
    parser.add_argument("--campus-log", default="../data/raw/assessor_campus_merges.csv")
    args = parser.parse_args()

    script_dir = pathlib.Path(__file__).resolve().parent
    osm_path = script_dir / args.osm
    assessor_path = script_dir / args.assessor
    sos_path = script_dir / args.sos
    enrichment_path = script_dir / args.enrichment
    overrides_path = script_dir / args.overrides
    output_path = script_dir / args.output
    metadata_path = script_dir / args.metadata
    embed_js_path = script_dir / args.embed_js
    review_csv_path = script_dir / args.review_csv
    campus_log_path = script_dir / args.campus_log
    output_path.parent.mkdir(parents=True, exist_ok=True)

    osm_payload = load_json(osm_path)
    assessor_payload = load_json(assessor_path)
    sos_payload = load_json(sos_path)
    enrichment, manual_records = load_enrichment(enrichment_path)
    override_rules = load_overrides(overrides_path)

    osm_records = [r for r in make_osm_records(osm_payload) if in_city_bbox(r["lat"], r["lon"])]
    assessor_records = [r for r in make_assessor_records(assessor_payload) if in_city_bbox(r["lat"], r["lon"])]
    sos_records = [r for r in make_sos_records(sos_payload) if in_city_bbox(r["lat"], r["lon"])]
    osm_records = apply_exclusions(osm_records, override_rules)
    assessor_records = apply_exclusions(assessor_records, override_rules)
    osm_records = dedupe_records(osm_records)
    merged, unmatched_assessor, _matched_ids = merge_records(osm_records, assessor_records)
    assessor_adds, campus_merges = collapse_campus_clusters(unmatched_assessor)
    for record in assessor_adds:
        record["review_reason"] = "assessor_included_on_map"
    merged.extend(assessor_adds)
    merged = merge_sos_records(merged, sos_records)
    merged.extend(manual_records)
    merged = apply_exclusions(merged, override_rules)
    merged = network_cluster_by_identity(merged)
    merged = dedupe_records(merged, distance_m=30.0)
    apply_enrichment(merged, enrichment)
    churches = finalize_records(merged)

    write_geojson(output_path, churches)
    write_review_csv(review_csv_path, assessor_adds)
    write_review_csv(campus_log_path, [
        {**item, "review_reason": "merged_into_campus_cluster"}
        for item in campus_merges
    ])

    metadata = {
        "title": "Hot Springs Church Map",
        "population": POPULATION,
        "population_source": POPULATION_SOURCE,
        "area_sq_mi": CITY_AREA_SQ_MI,
        "area_source": CITY_AREA_SOURCE,
        "osm_count": len(osm_records),
        "assessor_parcel_count": len(assessor_records),
        "assessor_included_count": len(assessor_adds),
        "assessor_campus_merges": len(campus_merges),
        "sos_count": len(sos_records),
        "manual_count": len(manual_records),
        "override_exclusions": len(override_rules),
        "assessor_candidate_count": len(assessor_payload.get("candidates", [])),
        "verified_count": sum(1 for c in churches if c["confidence"] == "high"),
        "church_count": len(churches),
        "normalized_at": datetime.now(timezone.utc).isoformat(),
        "last_updated": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "sources": [
            "OpenStreetMap Overpass API",
            "Arkansas GIS Office Planning_Cadastre",
            "Arkansas Secretary of State (optional)",
            "Manual enrichment.csv",
        ],
        "notes": (
            "OSM is the mapped seed. Assessor-only parcels are campus-collapsed "
            f"(within {int(CAMPUS_NETWORK_M)}m with similar names) before inclusion. "
            "Field-review exclusions live in data/raw/overrides.csv. "
            "Add manual churches in enrichment.csv with name, lat, lon. "
            "Optional SOS nonprofits live in data/raw/sos_churches.json."
        ),
    }
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    write_embed_js(output_path, metadata, embed_js_path)

    print(f"Normalized {len(churches)} churches to {output_path}")
    print(f"High-confidence matches: {metadata['verified_count']}")
    print(f"Assessor parcels collapsed into {len(assessor_adds)} campuses ({len(campus_merges)} parcels merged away)")
    print(f"Manual additions: {len(manual_records)} | SOS records: {len(sos_records)}")
    print(f"Included assessor campuses -> {review_csv_path}")
    print(f"Campus merge log -> {campus_log_path}")
    print(f"Wrote metadata to {metadata_path}")
    print(f"Wrote embed script to {embed_js_path}")


if __name__ == "__main__":
    main()
