#!/usr/bin/env python3
"""Build a Hugging Face object-detection dataset from labelme boxes + posters.csv.

Joins three things that already exist in this repo:

    photos/<project>/<batch>/*.jpg          the images
    annotations/labelme/<project>/<batch>/  one .json per annotated photo
    posters.csv                             per-photo survey metadata

and writes a self-contained `dataset/` directory in Hugging Face `imagefolder`
layout, plus an optional Ultralytics YOLO tree for training.

Usage:
    python3 scripts/build_dataset.py
    python3 scripts/build_dataset.py --yolo            # also emit dataset/yolo/
    python3 scripts/build_dataset.py --split           # group-aware train/val
    python3 scripts/build_dataset.py --allow-missing   # export partial batches

Boxes are exported as COCO-style [x, y, width, height] in absolute pixels,
top-left origin. The YOLO tree uses normalised centre-x/centre-y/w/h, as
Ultralytics expects.
"""

import argparse
import csv
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
POSTERS = ROOT / "posters.csv"
LABELME = ROOT / "annotations" / "labelme"
OUT = ROOT / "dataset"

DESIGNS = ROOT / "annotations" / "designs.json"


def load_designs():
    """Class list, read from the design registry.

    One class per poster *design*, not per physical form -- the same artwork
    appears as both a large wheatpasted sheet and a small sticker, and
    `posters.csv` already records which via `form`. The registry's order is the
    class index and is append-only; reordering it would silently change the
    meaning of every existing label file and every trained weight.
    """
    doc = json.loads(DESIGNS.read_text(encoding="utf-8"))
    designs = doc["designs"]
    return [d["id"] for d in designs], {d["id"]: d for d in designs}


CLASSES, DESIGN_BY_ID = load_designs()

# Photos carried by posters.csv but not by these fields are still exported;
# these are simply the columns that travel into the dataset card as metadata.
METADATA_COLUMNS = [
    "project", "batch", "captured_date", "captured_time",
    "latitude", "longitude", "altitude_m",
    "location_id", "form", "mounting", "condition", "status",
    "duplicate_of", "notes",
]


def rel(path):
    """Display paths relative to the repo when they are inside it, absolute when not."""
    try:
        return path.resolve().relative_to(ROOT)
    except ValueError:
        return path.resolve()


def load_rows(project=None):
    if not POSTERS.exists():
        sys.exit(f"missing {POSTERS}")
    with POSTERS.open(newline="", encoding="utf-8") as fh:
        rows = [r for r in csv.DictReader(fh) if not project or r["project"] == project]
    if not rows:
        sys.exit(f"no rows in posters.csv for project {project!r}")
    return rows


def labelme_path(row):
    """labelme writes <stem>.json into --output, mirroring the photo's stem."""
    photo = Path(row["photo"])
    return LABELME / photo.parent.relative_to("photos") / (photo.stem + ".json")


def read_boxes(path, width, height):
    """Return (boxes, categories): [(x, y, w, h)] in absolute pixels, clamped to
    the image, and the parallel class index of each.

    Accepts labelme `rectangle` shapes; a `polygon` is reduced to its bounding
    box so that a stray polygon does not silently drop an instance.
    """
    doc = json.loads(path.read_text(encoding="utf-8"))
    boxes, categories = [], []
    for shape in doc.get("shapes", []):
        label = shape.get("label")
        if label not in CLASSES:
            # A label that is not a registered design is almost always a typo or
            # a new artwork that nobody added to annotations/designs.json. Both
            # would silently drop instances, so neither is skipped quietly.
            sys.exit(
                f"{path}: shape labelled {label!r} is not a design in "
                f"{rel(DESIGNS)}. Known: {', '.join(CLASSES)}. "
                "Add it to the registry (append only) or fix the label."
            )
        pts = shape.get("points") or []
        if len(pts) < 2:
            continue
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        x0, y0 = max(0.0, min(xs)), max(0.0, min(ys))
        x1, y1 = min(float(width), max(xs)), min(float(height), max(ys))
        w, h = x1 - x0, y1 - y0
        if w < 1 or h < 1:
            print(f"    dropping degenerate box {w:.0f}x{h:.0f} in {path.name}", file=sys.stderr)
            continue
        boxes.append((round(x0, 1), round(y0, 1), round(w, 1), round(h, 1)))
        categories.append(CLASSES.index(label))
    # labelme records the size it was drawn against; a mismatch means the photo
    # was replaced after annotation and every box in the file is wrong.
    for key, actual in (("imageWidth", width), ("imageHeight", height)):
        recorded = doc.get(key)
        if recorded and int(recorded) != int(actual):
            sys.exit(
                f"{path}: annotated against {key}={recorded} but the photo is {actual}. "
                "Re-annotate; the boxes cannot be rescaled safely."
            )
    return boxes, categories


def assign_splits(records, do_split):
    """Split by location_id, never by photo.

    Several frames often show the same lamppost from a few paces apart (see
    `duplicate_of` in posters.csv). Splitting per-photo would put near-identical
    images in both train and validation and report a score that is mostly
    memorisation.
    """
    if not do_split:
        for rec in records:
            rec["split"] = "train"
        return
    locations = sorted({r["location_id"] or r["image_id"] for r in records})
    n_val = max(1, round(len(locations) * 0.25))
    val = set(locations[::max(1, len(locations) // n_val)][:n_val])
    for rec in records:
        rec["split"] = "validation" if (rec["location_id"] or rec["image_id"]) in val else "train"


def write_yolo(records, out):
    yolo = out / "yolo"
    for rec in records:
        split = "val" if rec["split"] == "validation" else "train"
        img_dir = yolo / "images" / split
        lbl_dir = yolo / "labels" / split
        img_dir.mkdir(parents=True, exist_ok=True)
        lbl_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / rec["photo"], img_dir / rec["file_name"])
        lines = []
        for cls, (x, y, w, h) in zip(rec["categories"], rec["boxes"]):
            cx = (x + w / 2) / rec["width"]
            cy = (y + h / 2) / rec["height"]
            lines.append(f"{cls} {cx:.6f} {cy:.6f} {w / rec['width']:.6f} {h / rec['height']:.6f}")
        (lbl_dir / (Path(rec["file_name"]).stem + ".txt")).write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    has_val = any(r["split"] == "validation" for r in records)
    (yolo / "data.yaml").write_text(
        "path: .\n"
        "train: images/train\n"
        f"val: images/{'val' if has_val else 'train'}\n"
        "names:\n"
        + "".join(f"  {i}: {c}\n" for i, c in enumerate(CLASSES)),
        encoding="utf-8",
    )
    return yolo


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", help="limit to one project, e.g. rebbe-posters")
    ap.add_argument("--yolo", action="store_true", help="also emit dataset/yolo/ for Ultralytics")
    ap.add_argument("--split", action="store_true", help="emit train/validation split by location")
    ap.add_argument("--allow-missing", action="store_true", help="export even if photos are unannotated")
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()

    rows = load_rows(args.project)
    records, missing = [], []
    for row in rows:
        path = labelme_path(row)
        if not path.exists():
            missing.append(row["photo"])
            continue
        photo = ROOT / row["photo"]
        doc = json.loads(path.read_text(encoding="utf-8"))
        width = int(doc.get("imageWidth") or 0)
        height = int(doc.get("imageHeight") or 0)
        if not width or not height:
            sys.exit(f"{path}: no imageWidth/imageHeight recorded")
        boxes, categories = read_boxes(path, width, height)
        records.append(
            {
                "image_id": row["id"],
                "file_name": f"{row['id']}.jpg",
                "photo": row["photo"],
                "source_file": photo.name,
                "width": width,
                "height": height,
                "boxes": boxes,
                "categories": categories,
                "location_id": row.get("location_id", ""),
                "meta": {k: row.get(k, "") for k in METADATA_COLUMNS},
            }
        )

    # A photo with no .json is UNANNOTATED. A photo with a .json and no shapes
    # is a verified negative -- a frame someone looked at and found nothing in.
    # Exporting the first as if it were the second teaches the model that real
    # posters are background, so it is an error by default.
    if missing:
        print(f"{len(missing)} of {len(rows)} photo(s) not yet annotated:", file=sys.stderr)
        for m in missing:
            print(f"  {m}", file=sys.stderr)
        if not args.allow_missing:
            sys.exit("\nrefusing to export a partial dataset (pass --allow-missing to override)")
        print("  -> excluded from the dataset (--allow-missing)\n", file=sys.stderr)

    if not records:
        sys.exit("nothing annotated yet -- run labelme first (see docs/annotation.md)")

    assign_splits(records, args.split)

    out = args.out
    if out.exists():
        shutil.rmtree(out)
    for rec in records:
        split_dir = out / "data" / rec["split"]
        split_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / rec["photo"], split_dir / rec["file_name"])

    for split in sorted({r["split"] for r in records}):
        lines = []
        for rec in [r for r in records if r["split"] == split]:
            objects = {
                "id": list(range(len(rec["boxes"]))),
                "category": rec["categories"],
                "bbox": [list(b) for b in rec["boxes"]],
                "area": [round(b[2] * b[3], 1) for b in rec["boxes"]],
            }
            entry = {
                "file_name": rec["file_name"],
                "image_id": rec["image_id"],
                "width": rec["width"],
                "height": rec["height"],
                "objects": objects,
                "source_file": rec["source_file"],
                **rec["meta"],
            }
            lines.append(json.dumps(entry, ensure_ascii=False))
        (out / "data" / split / "metadata.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")

    # Ship the registry with the data: the class list must travel with the
    # dataset, or a downloader has indices with no names to attach to them.
    shutil.copy2(DESIGNS, out / "designs.json")

    n_boxes = sum(len(r["boxes"]) for r in records)
    empties = sum(1 for r in records if not r["boxes"])
    write_card(out, records, n_boxes, empties)
    if args.yolo:
        write_yolo(records, out)

    print(f"\ndataset -> {rel(out)}")
    for split in sorted({r["split"] for r in records}):
        sel = [r for r in records if r["split"] == split]
        print(f"  {split}: {len(sel)} image(s), {sum(len(r['boxes']) for r in sel)} box(es)")
    if empties:
        print(f"  ({empties} verified-empty image(s) kept as negatives)")
    if args.yolo:
        print(f"  yolo tree -> {rel(out / 'yolo')}")


def write_card(out, records, n_boxes, empties):
    """Dataset card. Written for someone who finds this on the Hub with no context."""
    splits = sorted({r["split"] for r in records})
    areas = sorted(b[2] * b[3] for r in records for b in r["boxes"])
    if areas:
        smallest = f"{min(areas) ** 0.5:.0f} px" if areas else "n/a"
        median = f"{areas[len(areas) // 2] ** 0.5:.0f} px"
        size_note = (
            f"Instances are small relative to the frame: the smallest box is about "
            f"{smallest} on a side and the median about {median}, in 1920x2560 images. "
            "Detectors trained at 640 px will lose the smallest stickers entirely; "
            "train at higher resolution or on tiles."
        )
    else:
        size_note = ""
    per_design = {}
    for r in records:
        for c in r["categories"]:
            per_design[CLASSES[c]] = per_design.get(CLASSES[c], 0) + 1
    blocks = []
    for i, cid in enumerate(CLASSES):
        d = DESIGN_BY_ID[cid]
        forms = ", ".join(d.get("forms", [])) or "unspecified"
        blocks.append(
            f"### `{cid}` — {d['name']}\n\n"
            f"{d['description']}\n\n"
            f"- **Class index** `{i}` · **{per_design.get(cid, 0)} instance(s)** in this release\n"
            f"- **Physical forms:** {forms}\n"
            f"- **First recorded:** {d.get('first_seen', 'unknown')}\n"
            + (f"- {d['size_note']}\n" if d.get("size_note") else "")
            + (f"- {d['notes']}\n" if d.get("notes") else "")
        )
    design_block = "\n".join(blocks)
    n_classes = len(CLASSES)
    class_list = ", ".join(f"`{c}`" for c in CLASSES)
    projects = sorted({r["meta"]["project"] for r in records})
    lats = [float(r["meta"]["latitude"]) for r in records if r["meta"].get("latitude")]
    lons = [float(r["meta"]["longitude"]) for r in records if r["meta"].get("longitude")]
    bbox_note = (
        f"{min(lats):.4f}-{max(lats):.4f} N, {min(lons):.4f}-{max(lons):.4f} E"
        if lats and lons else "central Jerusalem"
    )
    dates = sorted({r["meta"]["captured_date"] for r in records if r["meta"].get("captured_date")})
    date_note = dates[0] if len(dates) == 1 else f"{dates[0]} to {dates[-1]}" if dates else "unknown"

    card = f"""---
license: cc-by-4.0
task_categories:
- object-detection
tags:
- object-detection
- street-photography
- urban-studies
- jerusalem
size_categories:
- n<1K
annotations_creators:
- expert-generated
language:
- he
---

# Jerusalem street poster sightings — detection dataset

Geotagged street photographs of a messianic postering campaign in central
Jerusalem, with bounding boxes around every campaign poster in frame. Each
image carries the GPS coordinates it was shot at, so the dataset supports both
detection and spatial analysis.

Each class is a **specific poster design**, not a generic "poster" category.
The intent is a recogniser that answers *which* known artwork is on the wall
and where its bounds are, so the class list grows as new designs are surveyed
rather than being redefined.

{design_block}

## At a glance

| | |
|---|---|
| Images | {len(records)} |
| Annotated instances | {n_boxes} |
| Classes | {n_classes} ({class_list}) |
| Splits | {", ".join(splits)} |
| Image size | 1920x2560 (portrait) |
| Captured | {date_note} |
| Area | {bbox_note} |
| Source repository | <https://github.com/danielrosehill/Jerusalem-Graffiti> |

## Class identifiers

Class indices come from `annotations/designs.json` in the source repository and
are **append-only**. A new design gets the next index; existing indices never
move. Reordering them would silently change the meaning of every published
label file and every model trained on an earlier release, so a released index
is permanent even if the design is later withdrawn.

Designs seen but not yet annotated are tracked separately in that file and are
deliberately *not* classes — a design becomes a class only when it has boxes.

## Format

Hugging Face `imagefolder` layout: `data/<split>/*.jpg` alongside a
`metadata.jsonl` keyed on `file_name`.

```python
from datasets import load_dataset
ds = load_dataset("imagefolder", data_dir="data")
```

Boxes are **COCO-style `[x, y, width, height]` in absolute pixels**, top-left
origin — not normalised, and not `[x1, y1, x2, y2]`. Getting this wrong is the
usual cause of a model that trains without error and detects nothing.

```json
{{"file_name": "...jpg", "objects": {{"id": [0], "category": [0],
  "bbox": [[842.0, 898.0, 114.0, 239.0]], "area": [27246.0]}}}}
```

An Ultralytics YOLO tree (normalised `cx cy w h`, with `data.yaml`) is emitted
alongside when the dataset is built with `--yolo`.

### Per-image metadata

Beyond the boxes, every row carries the survey fields: `latitude`, `longitude`,
`altitude_m`, `captured_date`, `captured_time`, `location_id`, `form`
(`wheatpaste` / `sticker` / `mixed`), `mounting` (`lamppost`, `hoarding`,
`wall`, ...), `condition` (`intact`, `sprayed`, `torn`, `faded`), `status`,
`duplicate_of` and a free-text `notes` field.

`form`, `mounting` and `condition` describe the image as a whole, not
individual boxes. A two-class wheatpaste/sticker variant can be derived from
`form` without re-annotating, except on rows marked `mixed`.

## Splitting

**Split on `location_id`, not on rows.** Several frames show the same lamppost
from a few paces apart — `duplicate_of` marks the clearest cases — so a random
per-image split puts near-identical photographs in both train and validation
and reports a score that is largely memorisation.
{"The published split already groups by location." if len(splits) > 1 else "This dataset ships as a single `train` split for that reason; do your own grouped split or grouped cross-validation."}

## Annotation protocol

Boxes were drawn by hand in [labelme](https://github.com/wkentaro/labelme) over
the full-resolution originals, one box per visible campaign poster.

- Partly occluded posters are boxed at their **visible extent**.
- Posters too blurred or distant to identify with confidence are **not** boxed;
  `notes` records several such judgements explicitly.
- Non-campaign material that looks similar — memorial notices, election
  flyers, blue-and-white "baruch haba" stickers of a different design, plain
  utility stickers — is deliberately **left unboxed** rather than labelled.
  Those are the confusions a detector will actually make, so they matter as
  background.
- {empties} image(s) contain no box. These are **verified negatives**, looked at
  and found to hold nothing, not unannotated files.

{size_note}

## Limitations

Read these before training anything you intend to trust.

- **It is small.** {len(records)} images and {n_boxes} instances, from a single
  walk. The working threshold for a genuine YOLO fine-tune is roughly 50 images
  and 150+ instances; this is below it. Treat it as a seed set, a benchmark for
  few-shot and open-vocabulary detectors, or a starting point to extend.
- **One photographer, one route, one time of day.** Late-afternoon light,
  one camera, one stretch of one street. No night, rain, or winter frames.
- **Correlated backgrounds.** Jaffa Road street furniture recurs constantly,
  so a model can learn "lamppost" as a proxy for "poster".
- **Instances are small and often high on poles**, frequently against blown-out
  sky, and several are damaged — over-sprayed, torn, or sun-bleached to
  near-illegibility. That damage is the interesting part of the survey and it
  is deliberately in-distribution here.
- **Not a census.** These are the sightings one person recorded, not every
  poster in the area, so counts carry no denominator.

## Provenance and intent

The photographs document postering in shared public space; the survey exists
because a municipal helpline had not acted on reports of it. Images are
published **as shot** — faces and number plates are not redacted, and passers-by
appear incidentally, as they do in ordinary street photography. If you appear in
a frame and want it removed, open an issue on the source repository.

The dataset records where campaign material was found. It is not evidence about
any individual, and nothing in it identifies who put the posters up. Do not use
it to make claims about people who happen to be visible in the frames.

## Citation

```bibtex
@misc{{jerusalem_poster_survey,
  title  = {{Jerusalem messianic poster sightings: a geotagged detection dataset}},
  author = {{Rosehill, Daniel}},
  year   = {{2026}},
  url    = {{https://github.com/danielrosehill/Jerusalem-Graffiti}}
}}
```

## Licence

Images and annotations: **CC BY 4.0**.
"""
    (out / "README.md").write_text(card, encoding="utf-8")


if __name__ == "__main__":
    main()
