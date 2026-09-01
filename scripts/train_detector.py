# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "ultralytics>=8.3.0",
#   "huggingface-hub>=0.34.0",
#   "pillow",
# ]
# ///
"""Fine-tune a YOLO11 detector on the poster dataset and push it to the Hub.

Self-contained: it pulls the dataset from the Hub, builds the YOLO tree itself
(including the train/validation split), trains, validates, and optionally
uploads the weights and a model card. Nothing depends on the local repo, so the
same file runs on a laptop or on HF Jobs unchanged.

On HF Jobs (a T4 is ample; this is a nano model on a few dozen images):

    hf jobs uv run --flavor t4-small --secrets HF_TOKEN \\
      scripts/train_detector.py -- --push danielrosehill/jerusalem-poster-detector

Locally:

    python3 scripts/train_detector.py --epochs 200 --device cpu

The split is grouped on `location_id`, never per-image: several frames show the
same lamppost from a few paces apart, so a random split would put near-copies
in both halves and report memorisation as accuracy.
"""

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

DATASET = "danielrosehill/jerusalem-poster-detection"


def log(msg):
    print(f"[train] {msg}", flush=True)


def fetch_dataset(repo, workdir):
    from huggingface_hub import snapshot_download

    log(f"downloading {repo}")
    path = snapshot_download(repo_id=repo, repo_type="dataset", local_dir=workdir / "hub")
    return Path(path)


def read_rows(root):
    rows = []
    for meta in sorted(root.glob("data/*/metadata.jsonl")):
        for line in meta.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                row["_dir"] = meta.parent
                rows.append(row)
    if not rows:
        sys.exit(f"no metadata.jsonl found under {root}/data")
    return rows


def grouped_split(rows, val_fraction, seed):
    """Hold out whole locations, chosen to land near `val_fraction` of the
    *instances* rather than of the locations.

    Falls back to grouping on image_id for any row without a location_id, which
    keeps each such photo intact on one side of the split rather than silently
    joining a group.

    Counting locations instead of instances gives a badly skewed split here,
    and it does so quietly: the locations are wildly uneven -- one hoarding
    carries 16 of the 26 boxes while five lampposts carry one each -- so an
    evenly spaced pick of 2 of 8 locations put 17 boxes in validation and left
    9 to train on. The largest group is therefore always kept in train, and
    validation is filled from the remainder until it reaches the target share.
    """
    groups = {}
    for row in rows:
        key = row.get("location_id") or row["image_id"]
        groups.setdefault(key, []).append(row)

    def n_boxes(key):
        return sum(len(r["objects"]["bbox"]) for r in groups[key])

    total = sum(n_boxes(k) for k in groups)
    target = total * val_fraction
    # Descending by instance count, then by name: deterministic, and it keeps
    # the richest location in train where it does the most good.
    ranked = sorted(groups, key=lambda k: (-n_boxes(k), k))
    val_keys, taken = set(), 0
    for key in ranked[1:]:
        if taken >= target:
            break
        val_keys.add(key)
        taken += n_boxes(key)
    if not val_keys:
        val_keys = {ranked[-1]}
        taken = n_boxes(ranked[-1])

    keys = sorted(groups)
    train = [r for k in keys if k not in val_keys for r in groups[k]]
    val = [r for k in keys if k in val_keys for r in groups[k]]
    log(f"{len(keys)} location(s) -> train {len(train)} img / val {len(val)} img; "
        f"instances {total - taken}/{taken} (held out: {', '.join(sorted(val_keys))})")
    return train, val


def write_yolo_tree(root, train_rows, val_rows, classes, out):
    if out.exists():
        shutil.rmtree(out)
    counts = {}
    for split, rows in (("train", train_rows), ("val", val_rows)):
        img_dir = out / "images" / split
        lbl_dir = out / "labels" / split
        img_dir.mkdir(parents=True, exist_ok=True)
        lbl_dir.mkdir(parents=True, exist_ok=True)
        n_box = 0
        for row in rows:
            src = row["_dir"] / row["file_name"]
            shutil.copy2(src, img_dir / row["file_name"])
            W, H = row["width"], row["height"]
            lines = []
            for cat, (x, y, w, h) in zip(row["objects"]["category"], row["objects"]["bbox"]):
                lines.append(
                    f"{cat} {(x + w / 2) / W:.6f} {(y + h / 2) / H:.6f} {w / W:.6f} {h / H:.6f}"
                )
                n_box += 1
            (lbl_dir / (Path(row["file_name"]).stem + ".txt")).write_text(
                "\n".join(lines) + ("\n" if lines else ""), encoding="utf-8"
            )
        counts[split] = (len(rows), n_box)
    yaml = (
        f"path: {out.resolve()}\n"
        "train: images/train\n"
        "val: images/val\n"
        "names:\n" + "".join(f"  {i}: {c}\n" for i, c in enumerate(classes))
    )
    (out / "data.yaml").write_text(yaml, encoding="utf-8")
    for split, (n_img, n_box) in counts.items():
        log(f"{split}: {n_img} image(s), {n_box} box(es)")
    if counts["val"][1] == 0:
        log("WARNING: validation split contains no boxes; mAP will be meaningless")
    return out / "data.yaml"


def class_names(root):
    """Class order is the dataset's, taken from the card's registry section if
    present and otherwise reconstructed from the highest category index seen."""
    designs = root / "designs.json"
    if designs.exists():
        return [d["id"] for d in json.loads(designs.read_text(encoding="utf-8"))["designs"]]
    rows = read_rows(root)
    top = max((c for r in rows for c in r["objects"]["category"]), default=0)
    names = [f"class-{i}" for i in range(top + 1)]
    log(f"no designs.json in the dataset; using placeholder names {names}")
    return names


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dataset", default=DATASET)
    ap.add_argument("--model", default="yolo11n.pt", help="COCO-pretrained starting weights")
    ap.add_argument("--epochs", type=int, default=300)
    ap.add_argument("--imgsz", type=int, default=1280,
                    help="posters occupy as little as 40x70 px in a 1920x2560 frame; "
                         "at 640 the smallest vanish entirely")
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--device", default=None, help="cpu, 0, ... (default: auto)")
    ap.add_argument("--val-fraction", type=float, default=0.25)
    ap.add_argument("--all-data", action="store_true",
                    help="train on every image and validate on the same set. The "
                         "reported mAP then measures memorisation and is not a "
                         "generalisation estimate -- but with a few dozen instances "
                         "the held-out images are worth more as training signal "
                         "than as a measurement, so this is the sane way to fit the "
                         "weights you actually publish. Measure with a split first.")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--lr0", type=float, default=0.001,
                    help="Ultralytics' 0.01 default assumes far more data; on a "
                         "few dozen instances it drives the model into a "
                         "degenerate all-foreground solution")
    ap.add_argument("--freeze", type=int, default=10,
                    help="freeze the first N backbone layers; on a few dozen images "
                         "full fine-tuning overfits fast")
    ap.add_argument("--workdir", type=Path, default=Path("runs/poster-detector"))
    ap.add_argument("--push", metavar="REPO_ID", help="push weights + card to this HF model repo")
    ap.add_argument("--private", action="store_true", help="create the model repo private")
    args = ap.parse_args()

    workdir = args.workdir.resolve()
    workdir.mkdir(parents=True, exist_ok=True)

    root = fetch_dataset(args.dataset, workdir)
    classes = class_names(root)
    log(f"classes: {classes}")
    rows = read_rows(root)
    if args.all_data:
        train_rows = val_rows = rows
        log(f"--all-data: training on all {len(rows)} image(s); "
            "reported metrics measure memorisation, not generalisation")
    else:
        train_rows, val_rows = grouped_split(rows, args.val_fraction, args.seed)
    data_yaml = write_yolo_tree(root, train_rows, val_rows, classes, workdir / "yolo")

    from ultralytics import YOLO

    model = YOLO(args.model)
    log(f"training {args.model} for {args.epochs} epoch(s) at imgsz={args.imgsz}")
    model.train(
        data=str(data_yaml),
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        device=args.device,
        freeze=args.freeze,
        lr0=args.lr0,
        seed=args.seed,
        project=str(workdir),
        name="train",
        exist_ok=True,
        patience=50,
        cos_lr=True,
        close_mosaic=10,
        # Hebrew lettering is a large part of what separates one design from the
        # next, and a mirrored poster does not exist in the street. Horizontal
        # flip is therefore off, and the lost augmentation is bought back with
        # more aggressive scale and translation.
        fliplr=0.0,
        scale=0.7,
        translate=0.2,
        degrees=5.0,
        plots=True,
    )

    log("validating on the held-out locations")
    metrics = model.val(data=str(data_yaml), imgsz=args.imgsz, device=args.device,
                        project=str(workdir), name="val", exist_ok=True)
    summary = {
        "map50": float(metrics.box.map50),
        "map50_95": float(metrics.box.map),
        "precision": float(metrics.box.mp),
        "recall": float(metrics.box.mr),
        "classes": classes,
        "train_images": len(train_rows),
        "val_images": len(val_rows),
        "val_locations": sorted({r.get("location_id") or r["image_id"] for r in val_rows}),
        "held_out": not args.all_data,
        "imgsz": args.imgsz,
        "epochs": args.epochs,
        "base_model": args.model,
        "lr0": args.lr0,
        "freeze": args.freeze,
        "dataset": args.dataset,
    }
    log(json.dumps(summary, indent=2))
    (workdir / "metrics.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    best = workdir / "train" / "weights" / "best.pt"
    if not best.exists():
        sys.exit(f"training produced no weights at {best}")
    log(f"weights: {best} ({best.stat().st_size / 1e6:.1f} MB)")

    if args.push:
        push(args, best, workdir, summary, classes)


def push(args, best, workdir, summary, classes):
    from huggingface_hub import HfApi

    if not (os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")):
        log("no HF_TOKEN in the environment; relying on a cached login")
    api = HfApi()
    api.create_repo(args.push, repo_type="model", exist_ok=True, private=args.private)

    staging = workdir / "push"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    shutil.copy2(best, staging / "best.pt")
    shutil.copy2(workdir / "metrics.json", staging / "metrics.json")
    for plot in ("results.png", "confusion_matrix.png", "PR_curve.png"):
        src = workdir / "train" / plot
        if src.exists():
            shutil.copy2(src, staging / plot)
    (staging / "README.md").write_text(model_card(args, summary, classes), encoding="utf-8")

    api.upload_folder(folder_path=str(staging), repo_id=args.push, repo_type="model")
    log(f"pushed -> https://huggingface.co/{args.push}")


def model_card(args, s, classes):
    # A sibling run with identical hyperparameters, evaluated on locations it
    # never saw. Reported separately because the shipped weights are usually
    # refit on everything afterwards, and the two numbers mean different things.
    ho = s.get("heldout")
    heldout_block = ""
    if ho:
        heldout_block = f"""
### Held-out evaluation

The shipped weights above are fitted on all {s['train_images']} image(s). To
measure generalisation, an identically configured run held out whole locations
({', '.join(ho['val_locations'])}) and never saw them:

| Metric | Held out |
|---|---|
| mAP@50 | {ho['map50']:.3f} |
| mAP@50-95 | {ho['map50_95']:.3f} |
| Precision | {ho['precision']:.3f} |
| Recall | {ho['recall']:.3f} |
| Train / val images | {ho['train_images']} / {ho['val_images']} |

**These are the numbers to judge the model by.** Inspected by eye at
`conf=0.25`, it finds the real posters on unseen lampposts but also fires on a
passer-by's dark coat and on bright sky-and-building patches, which is what a
precision of {ho['precision']:.2f} looks like in practice."""
    warn = ""
    if not s.get("held_out", True):
        warn = (
            "\n> **Validation was not held out.** These weights are fitted on every "
            "image in the dataset, so the figures below measure how well the model "
            "reproduces what it was shown. They are not an estimate of performance "
            "on new photographs. The held-out numbers are in the training log.\n"
        )
    elif s["val_images"] < 5 or s["map50"] < 0.1:
        warn = (
            "\n> **The validation set is tiny.** These figures come from "
            f"{s['val_images']} held-out image(s). Treat them as a smoke test that "
            "training ran, not as a measurement of how well this generalises.\n"
        )
    return f"""---
license: cc-by-4.0
library_name: ultralytics
pipeline_tag: object-detection
tags:
- ultralytics
- yolo11
- object-detection
- street-photography
datasets:
- {args.dataset}
---

# Jerusalem street poster detector

Fine-tune of `{s['base_model']}` that locates specific poster designs in street
photographs and names which design it found. Trained on
[{args.dataset}](https://huggingface.co/datasets/{args.dataset}).

**This is a proof of concept**: that a small detector, trained on a few dozen
hand-drawn boxes, can support graffiti and flyposting workflows — surveying
what is up, identifying which known artwork it is, and checking afterwards
whether it came down. It is not a finished production model, and the honest
reading of its numbers is at the bottom of this card.

Each class is one **artwork**, not a generic "poster" category, so the model
answers *which* known design is on the wall and where its bounds are. The class
list grows as new designs are surveyed; indices are append-only.

## Classes

{chr(10).join(f"- `{i}` — `{c}`" for i, c in enumerate(classes))}

## Results
{warn}
| Metric | Value |
|---|---|
| mAP@50 | {s['map50']:.3f} |
| mAP@50-95 | {s['map50_95']:.3f} |
| Precision | {s['precision']:.3f} |
| Recall | {s['recall']:.3f} |
| Train images | {s['train_images']} |
| Val images | {s['val_images']} |
| Image size | {s['imgsz']} |
| Epochs | {s['epochs']} |
{heldout_block}

Validation held out whole **locations** ({', '.join(s['val_locations'])}), not
random images: several frames in the dataset show the same lamppost from a few
paces apart, and splitting per-image would score memorisation.

## Usage

```python
from ultralytics import YOLO
from huggingface_hub import hf_hub_download

weights = hf_hub_download("{args.push}", "best.pt")
model = YOLO(weights)

for r in model.predict("street_photo.jpg", imgsz={s['imgsz']}, conf=0.25):
    for box in r.boxes:
        print(model.names[int(box.cls)], box.xyxy[0].tolist(), float(box.conf))
```

**Predict at the image size it was trained on.** Instances are small — some
occupy under 0.1% of the frame — so running at the 640 default will miss them.

## Limitations

Trained on {s['train_images']} photographs from one photographer's walk down one
street on one afternoon, so it has seen a narrow slice of lighting, weather and
background. At that size the hyperparameters matter more than usual: the first
run of this model, at Ultralytics' default `lr0=0.01` with an unfrozen backbone
and a batch larger than the training set, collapsed into predicting the whole
frame as poster at confidence 1.0 while its training loss fell smoothly. The
shipped configuration is `lr0={s.get('lr0', 0.001)}`, `freeze={s.get('freeze', 10)}`,
`batch=4`. Posters appear intact,
over-sprayed, torn and sun-bleached; other street material it has never seen —
memorial notices, election flyers, other stickers — is exactly what it is most
likely to fire on falsely. Verify before trusting counts.

Reproduce with `scripts/train_detector.py` in
<https://github.com/danielrosehill/Jerusalem-Graffiti>.
"""


if __name__ == "__main__":
    main()
