#!/usr/bin/env python3
"""Build the Take-me-here field sheet for one batch.

A PDF of every photographed poster with a tappable Google Maps directions link,
meant to be opened on a phone in the street.

Usage:
    python3 scripts/build_pdf.py rebbe-posters/3108
    python3 scripts/build_pdf.py rebbe-posters/3108 -o /tmp/sheet.pdf
"""

import argparse
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TEMPLATE = REPO / "templates" / "take-me-here.typ"


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("batch", help="project/batch under photos/, e.g. rebbe-posters/3108")
    ap.add_argument("-o", "--output", type=Path)
    ap.add_argument("--subtitle", default="")
    args = ap.parse_args()

    csv_path = REPO / "photos" / args.batch / "geolocations.csv"
    if not csv_path.exists():
        sys.exit(f"no geolocations.csv at {csv_path}\n"
                 f"run: python3 scripts/exif_to_csv.py photos/{args.batch}")

    output = args.output or REPO / "pdf" / f"take-me-here-{args.batch.replace('/', '-')}.pdf"
    output.parent.mkdir(parents=True, exist_ok=True)

    cmd = ["typst", "compile", "--root", str(REPO),
           "--input", f"batch={args.batch}",
           "--input", f"subtitle={args.subtitle}",
           str(TEMPLATE), str(output)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        sys.exit(result.stderr.strip() or "typst failed")

    print(f"{output} ({output.stat().st_size / 1_048_576:.1f} MB)")


if __name__ == "__main__":
    main()
