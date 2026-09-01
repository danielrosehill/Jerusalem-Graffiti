#!/usr/bin/env python3
"""Build a geolocation CSV from a folder of Timemark (Android) photos.

Reads EXIF directly with exiftool -- no network calls, no reverse geocoding.
Timemark writes standard EXIF GPS tags alongside its burnt-in watermark, so the
coordinates come out of the file rather than off the pixels.

Usage:
    python3 scripts/exif_to_csv.py photos/3108
    python3 scripts/exif_to_csv.py photos/3108 -o photos/3108/geolocations.csv
"""

import argparse
import csv
import json
import re
import subprocess
import sys
from pathlib import Path

# Timemark appends custom field tags to the filename as "(Key-Value)" groups,
# e.g. "2026-08-31 17.29.47__(Poster-Rebbe)_(Quantity-Single).jpg"
TAG_RE = re.compile(r"\(([^()-]+)-([^()]+)\)")

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".heic", ".webp"}

FIELDS = [
    "filename",
    "captured_local",
    "utc_offset",
    "latitude",
    "longitude",
    "altitude_m",
    "maps_url",
    "timemark_tags",
    "camera_make",
    "camera_model",
    "software",
    "width",
    "height",
]


def read_exif(paths):
    """Return exiftool's JSON output for the given files, numeric where possible."""
    cmd = [
        "exiftool", "-n", "-j", "-charset", "filename=utf8",
        "-FileName", "-DateTimeOriginal", "-OffsetTimeOriginal",
        "-GPSLatitude", "-GPSLongitude", "-GPSAltitude",
        "-Make", "-Model", "-Software", "-ImageWidth", "-ImageHeight",
        *[str(p) for p in paths],
    ]
    out = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
    return json.loads(out) if out.strip() else []


def parse_tags(filename):
    return ";".join(f"{k.strip()}={v.strip()}" for k, v in TAG_RE.findall(filename))


def normalise(entry):
    lat, lon = entry.get("GPSLatitude"), entry.get("GPSLongitude")
    dt = (entry.get("DateTimeOriginal") or "").replace(":", "-", 2)
    return {
        "filename": entry.get("FileName", ""),
        "captured_local": dt,
        "utc_offset": entry.get("OffsetTimeOriginal", ""),
        "latitude": f"{lat:.7f}" if isinstance(lat, (int, float)) else "",
        "longitude": f"{lon:.7f}" if isinstance(lon, (int, float)) else "",
        "altitude_m": f"{entry['GPSAltitude']:.1f}" if isinstance(entry.get("GPSAltitude"), (int, float)) else "",
        "maps_url": f"https://www.google.com/maps?q={lat:.7f},{lon:.7f}" if isinstance(lat, (int, float)) else "",
        "timemark_tags": parse_tags(entry.get("FileName", "")),
        "camera_make": entry.get("Make", ""),
        "camera_model": entry.get("Model", ""),
        "software": entry.get("Software", ""),
        "width": entry.get("ImageWidth", ""),
        "height": entry.get("ImageHeight", ""),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder", type=Path, help="folder of photos, e.g. photos/3108")
    ap.add_argument("-o", "--output", type=Path, help="CSV path (default: <folder>/geolocations.csv)")
    args = ap.parse_args()

    if not args.folder.is_dir():
        sys.exit(f"not a directory: {args.folder}")

    photos = sorted(p for p in args.folder.iterdir() if p.suffix.lower() in IMAGE_SUFFIXES)
    if not photos:
        sys.exit(f"no images found in {args.folder}")

    rows = [normalise(e) for e in read_exif(photos)]
    rows.sort(key=lambda r: (r["captured_local"], r["filename"]))

    output = args.output or args.folder / "geolocations.csv"
    with output.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    missing = [r["filename"] for r in rows if not r["latitude"]]
    print(f"{len(rows)} rows -> {output}")
    if missing:
        print(f"warning: no GPS in {len(missing)} file(s): {', '.join(missing)}", file=sys.stderr)


if __name__ == "__main__":
    main()
