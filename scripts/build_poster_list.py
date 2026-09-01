#!/usr/bin/env python3
"""Build posters.csv, the survey's single source of truth.

Reads every photos/<project>/<batch>/geolocations.csv, merges them into one
tracked list, and preserves anything edited by hand. The PDF is generated from
this file, so the chain is:

    photos -> geolocations.csv (EXIF) -> posters.csv (tracking) -> PDF

Rows are keyed on a stable id derived from the capture time, so inserting or
removing a photo never reassigns another row's identity and never loses an edit.

Usage:
    python3 scripts/build_poster_list.py
    python3 scripts/build_poster_list.py --check   # validate, write nothing
"""

import argparse
import csv
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUTPUT = REPO / "posters.csv"
CONFIG = json.loads((REPO / "config.json").read_text(encoding="utf-8"))

# Everything before `notes` is generated from EXIF and overwritten on rebuild.
# Everything from `poster_count` onward is hand-maintained and preserved.
GENERATED = [
    "id", "project", "batch", "photo", "captured_date", "captured_time",
    "latitude", "longitude", "altitude_m", "maps_url", "directions_url",
    "location_id", "location_photos", "location_posters", "timemark_tags",
]
TRACKED = [
    "duplicate_of", "poster_count", "form", "mounting", "condition", "status",
    "reported_date", "reported_by", "report_ref", "notes",
]
FIELDS = GENERATED + TRACKED


def make_id(project, batch, time_str, seen):
    base = f"{project}-{batch}-{time_str.replace(':', '')}"
    if base not in seen:
        seen.add(base)
        return base
    n = 2
    while f"{base}-{n}" in seen:
        n += 1
    seen.add(f"{base}-{n}")
    return f"{base}-{n}"


def read_existing():
    if not OUTPUT.exists():
        return {}
    with OUTPUT.open(encoding="utf-8") as fh:
        return {r["id"]: r for r in csv.DictReader(fh)}


def collect():
    """One row per photograph, from every batch's geolocations.csv."""
    existing = read_existing()
    defaults, reporter = CONFIG["defaults"], CONFIG["reporter"]
    seen, rows = set(), []

    for csv_path in sorted(REPO.glob("photos/*/*/geolocations.csv")):
        batch_dir = csv_path.parent
        project, batch = batch_dir.parts[-2], batch_dir.parts[-1]
        with csv_path.open(encoding="utf-8") as fh:
            for src in csv.DictReader(fh):
                date, _, time_str = src["captured_local"].partition(" ")
                rid = make_id(project, batch, time_str, seen)
                prior = existing.get(rid, {})
                lat, lon = src["latitude"], src["longitude"]
                dest = f"{lat},{lon}"

                row = {
                    "id": rid,
                    "project": project,
                    "batch": batch,
                    "photo": f"photos/{project}/{batch}/{src['filename']}",
                    "captured_date": date,
                    "captured_time": time_str,
                    "latitude": lat,
                    "longitude": lon,
                    "altitude_m": src["altitude_m"],
                    "maps_url": f"https://www.google.com/maps/search/?api=1&query={dest}",
                    "directions_url": f"https://www.google.com/maps/dir/?api=1&destination={dest}",
                    "timemark_tags": src["timemark_tags"],
                }
                # Hand-maintained columns survive every rebuild.
                for field in TRACKED:
                    row[field] = prior.get(field, "")
                if not prior:
                    row["status"] = defaults["status"]
                    row["condition"] = defaults["condition"]
                    row["form"] = defaults["form"]
                    row["mounting"] = defaults["mounting"]
                    row["reported_by"] = reporter
                    row["reported_date"] = date if defaults["status"] == "reported" else ""
                rows.append(row)

    # Photographs taken from one spot share a coordinate to 7dp. Group them so
    # the field sheet can say "8 locations, 13 photographs" rather than sending
    # someone to the same lamppost four times.
    order, counts = {}, {}
    for r in rows:
        key = (r["latitude"], r["longitude"])
        order.setdefault(key, f"L{len(order) + 1}")
        counts[key] = counts.get(key, 0) + 1
    # A location's total is the sum over its non-duplicate rows. Photographing
    # the same pole twice must not double the count, but four different pieces
    # of artwork around one corner must still add up -- which is a judgement
    # only a person looking at the photographs can make, so it is recorded
    # explicitly in duplicate_of rather than inferred from the coordinate.
    totals, partial = {}, {}
    for r in rows:
        key = (r["latitude"], r["longitude"])
        if r.get("duplicate_of"):
            continue
        if r["poster_count"]:
            totals[key] = totals.get(key, 0) + int(r["poster_count"])
        else:
            partial[key] = True
    for r in rows:
        key = (r["latitude"], r["longitude"])
        r["location_id"] = order[key]
        r["location_photos"] = str(counts[key])
        total = totals.get(key, 0)
        # "+" means at least this many: some artwork here was not countable.
        r["location_posters"] = f"{total}+" if partial.get(key) else str(total)

    stale = set(existing) - seen
    return rows, stale


def validate(rows):
    problems = []
    for row in rows:
        for field, allowed in CONFIG["vocabularies"].items():
            value = row.get(field, "")
            if value and value not in allowed:
                problems.append(f'{row["id"]}: {field}="{value}" not in {allowed}')
        if row["poster_count"] and not row["poster_count"].isdigit():
            problems.append(f'{row["id"]}: poster_count="{row["poster_count"]}" is not a number')
    return problems


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="validate only, write nothing")
    args = ap.parse_args()

    rows, stale = collect()
    if not rows:
        sys.exit("no geolocations.csv found; run scripts/exif_to_csv.py first")

    rows.sort(key=lambda r: (r["captured_date"], r["captured_time"], r["id"]))
    problems = validate(rows)
    for p in problems:
        print(f"invalid: {p}", file=sys.stderr)
    for s in sorted(stale):
        print(f"warning: {s} is in posters.csv but its photo is gone; "
              f"row dropped, edits lost", file=sys.stderr)

    if args.check:
        print(f"{len(rows)} rows checked, {len(problems)} problem(s)")
        sys.exit(1 if problems else 0)
    if problems:
        sys.exit("refusing to write while values are invalid; fix them or widen "
                 "the vocabulary in config.json")

    with OUTPUT.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    days = sorted({r["captured_date"] for r in rows})
    locs = {r["location_id"] for r in rows}
    counted = sum(int(r["poster_count"]) for r in rows if r["poster_count"])
    print(f"{len(rows)} photographs at {len(locs)} location(s) across {len(days)} day(s) "
          f"-> {OUTPUT.relative_to(REPO)}")
    print(f"{counted} poster instances counted "
          f"({sum(1 for r in rows if not r['poster_count'])} rows uncounted)")


if __name__ == "__main__":
    main()
