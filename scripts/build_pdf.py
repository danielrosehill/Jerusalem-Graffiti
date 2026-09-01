#!/usr/bin/env python3
"""Build the Take-me-here field sheet from posters.csv.

A PDF of every photographed poster, sectioned by the day it was photographed,
each entry carrying a tappable Google Maps directions link and a table of its
tracked status. Meant to be opened on a phone in the street.

posters.csv is the source of truth; this is a pure render of it. Rebuild after
every edit rather than annotating the PDF.

Usage:
    python3 scripts/build_pdf.py
    python3 scripts/build_pdf.py --project rebbe-posters
    python3 scripts/build_pdf.py -o /tmp/sheet.pdf
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
    ap.add_argument("--project", default="", help="limit to one project, e.g. rebbe-posters")
    ap.add_argument("-o", "--output", type=Path)
    ap.add_argument("--subtitle", default="")
    args = ap.parse_args()

    csv_path = REPO / "posters.csv"
    if not csv_path.exists():
        sys.exit("no posters.csv\nrun: python3 scripts/build_poster_list.py")

    suffix = f"-{args.project}" if args.project else ""
    output = args.output or REPO / "pdf" / f"take-me-here{suffix}.pdf"
    output.parent.mkdir(parents=True, exist_ok=True)

    cmd = ["typst", "compile", "--root", str(REPO),
           "--input", f"project={args.project}",
           "--input", f"subtitle={args.subtitle}",
           str(TEMPLATE), str(output)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        sys.exit(result.stderr.strip() or "typst failed")

    print(f"{output} ({output.stat().st_size / 1_048_576:.1f} MB)")


if __name__ == "__main__":
    main()
