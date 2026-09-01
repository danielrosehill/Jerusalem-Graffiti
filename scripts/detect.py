# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "ultralytics>=8.3.0",
#   "huggingface-hub>=0.34.0",
#   "pillow",
# ]
# ///
"""Run the published poster detector over photographs.

Weights come from the Hugging Face Hub, not from a file in this repo -- the
model is a published artifact with its own version history, and the repo holds
only the code that produced it. `huggingface_hub` caches the download, so the
network is touched once.

Usage:
    python3 scripts/detect.py photos/rebbe-posters/3108
    python3 scripts/detect.py photo.jpg --annotate out/
    python3 scripts/detect.py photos/ --json findings.json --conf 0.4
"""

import argparse
import json
import sys
from pathlib import Path

MODEL_REPO = "danielrosehill/jerusalem-poster-detector"
WEIGHTS = "best.pt"
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("target", type=Path, help="image file or directory")
    ap.add_argument("--model", default=MODEL_REPO, help="HF model repo, or a path to local weights")
    ap.add_argument("--conf", type=float, default=0.25)
    ap.add_argument("--imgsz", type=int, default=None,
                    help="defaults to the size the model was trained at, read from the weights")
    ap.add_argument("--annotate", type=Path, metavar="DIR", help="write boxed copies here")
    ap.add_argument("--json", type=Path, metavar="FILE", help="write findings as JSON")
    args = ap.parse_args()

    from ultralytics import YOLO

    src = Path(args.model)
    if src.exists():
        weights = str(src)
    else:
        from huggingface_hub import hf_hub_download
        weights = hf_hub_download(args.model, WEIGHTS)
    model = YOLO(weights)

    # Instances get down to roughly 40x70 px in a 1920x2560 frame, so the 640
    # default would drop the smallest before the model ever sees them. Prefer
    # the training size recorded in the checkpoint over Ultralytics' default.
    imgsz = args.imgsz or int(getattr(model, "overrides", {}).get("imgsz", 0) or 0) or 960

    if args.target.is_dir():
        images = sorted(p for p in args.target.rglob("*") if p.suffix.lower() in IMAGE_SUFFIXES)
    else:
        images = [args.target]
    if not images:
        sys.exit(f"no images under {args.target}")

    if args.annotate:
        args.annotate.mkdir(parents=True, exist_ok=True)

    findings, total = [], 0
    for image in images:
        result = model.predict(str(image), imgsz=imgsz, conf=args.conf, verbose=False)[0]
        boxes = []
        for box in result.boxes:
            x1, y1, x2, y2 = (round(v, 1) for v in box.xyxy[0].tolist())
            boxes.append({
                "design": model.names[int(box.cls)],
                "confidence": round(float(box.conf), 4),
                "bbox": [x1, y1, round(x2 - x1, 1), round(y2 - y1, 1)],
            })
        boxes.sort(key=lambda b: -b["confidence"])
        total += len(boxes)
        findings.append({"photo": str(image), "detections": boxes})
        summary = ", ".join(f"{b['design']} {b['confidence']:.2f}" for b in boxes) or "nothing"
        print(f"{image.name}: {len(boxes)} -- {summary}")
        if args.annotate and boxes:
            result.save(filename=str(args.annotate / image.name))

    print(f"\n{total} detection(s) across {len(images)} image(s) at conf>={args.conf}, imgsz={imgsz}")
    if args.json:
        args.json.write_text(json.dumps(findings, indent=2) + "\n", encoding="utf-8")
        print(f"-> {args.json}")


if __name__ == "__main__":
    main()
