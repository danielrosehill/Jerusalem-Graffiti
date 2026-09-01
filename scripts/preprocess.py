#!/usr/bin/env python3
"""Local, CPU-only preprocessing for a batch of field photos.

Three passes, all offline, no model training and no network calls:

  posters  detect campaign posters/stickers by matching reference crops with
           ORB features + RANSAC homography, and draw boxes
  faces    detect bystander faces with YuNet and pixelate them
  plates   detect Israeli yellow number plates by colour and shape, and pixelate

Originals are never modified. Everything is written under derived/.

Usage:
    python3 scripts/preprocess.py photos/rebbe-posters/3108
    python3 scripts/preprocess.py photos/rebbe-posters/3108 --no-plates
    python3 scripts/preprocess.py photos/rebbe-posters/3108 --face-scales 1.0
"""

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np

REPO = Path(__file__).resolve().parent.parent
YUNET = REPO / "models" / "face_detection_yunet_2023mar.onnx"
EXEMPLAR_DIR = REPO / "references" / "posters"
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}

# Reference crops are named "<class>-<slug>.jpg"; the prefix before the first
# hyphen is the label written into the detections and the labelme pre-labels.
CLASSES = ("poster", "sticker")

BOX_COLOUR = {"poster": (60, 220, 60), "sticker": (60, 200, 255)}

RATIO = 0.78          # Lowe ratio test
EXEMPLAR_FEATURES = 4000
SCENE_FEATURES = 12000


# --------------------------------------------------------------------------- geometry

def iou(a, b):
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ix = max(0, min(ax + aw, bx + bw) - max(ax, bx))
    iy = max(0, min(ay + ah, by + bh) - max(ay, by))
    inter = ix * iy
    union = aw * ah + bw * bh - inter
    return inter / union if union > 0 else 0.0


def containment(inner, outer):
    """Fraction of `inner` that lies inside `outer`.

    IoU is the wrong test for a small box inside a big one: a face on a poster
    scores about 0.04, so an IoU threshold never fires and the protection is
    silently dead. Containment is the question actually being asked.
    """
    ix, iy, iw, ih = inner
    ox, oy, ow, oh = outer
    w = max(0, min(ix + iw, ox + ow) - max(ix, ox))
    h = max(0, min(iy + ih, oy + oh) - max(iy, oy))
    area = iw * ih
    return (w * h) / area if area > 0 else 0.0


def nms(boxes, scores, thr=0.35):
    order = sorted(range(len(boxes)), key=lambda i: scores[i], reverse=True)
    keep = []
    while order:
        i = order.pop(0)
        keep.append(i)
        order = [j for j in order if iou(boxes[i], boxes[j]) < thr]
    return keep


def quad_to_box(quad, shape):
    h, w = shape[:2]
    xs, ys = quad[:, 0], quad[:, 1]
    x0, y0 = max(0, int(xs.min())), max(0, int(ys.min()))
    x1, y1 = min(w, int(xs.max())), min(h, int(ys.max()))
    return [x0, y0, x1 - x0, y1 - y0]


# --------------------------------------------------------------------------- posters

def load_exemplars(directory):
    orb = cv2.ORB_create(nfeatures=EXEMPLAR_FEATURES)
    out = []
    for path in sorted(directory.glob("*.jpg")):
        label = path.stem.split("-", 1)[0]
        if label not in CLASSES:
            print(f"skipping {path.name}: prefix is not one of {CLASSES}", file=sys.stderr)
            continue
        img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        kp, des = orb.detectAndCompute(img, None)
        if des is None or len(kp) < 20:
            print(f"skipping {path.name}: too few ORB features", file=sys.stderr)
            continue
        out.append({"name": path.name, "label": label, "shape": img.shape, "kp": kp, "des": des})
    return out


def load_corrected_labels(label_dir, stem):
    """Hand-corrected labelme rectangles for one photo, if they exist.

    Auto pre-labels live in labels/.../auto/ and are rewritten every run;
    anything at the top level was corrected by a human and is never overwritten.
    """
    path = label_dir / f"{stem}.json"
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    out = []
    for shape in data.get("shapes", []):
        if shape.get("shape_type") != "rectangle":
            continue
        (x0, y0), (x1, y1) = shape["points"]
        out.append({
            "label": shape.get("label", "poster"),
            "box": [int(min(x0, x1)), int(min(y0, y1)), int(abs(x1 - x0)), int(abs(y1 - y0))],
        })
    return out


def sane_quad(quad, exemplar_shape, scene_shape):
    """Reject homographies that produced a degenerate or implausible shape."""
    area = cv2.contourArea(quad.astype(np.float32))
    scene_area = scene_shape[0] * scene_shape[1]
    if not (0.0004 * scene_area < area < 0.5 * scene_area):
        return False
    if not cv2.isContourConvex(quad.astype(np.float32)):
        return False
    sides = [np.linalg.norm(quad[i] - quad[(i + 1) % 4]) for i in range(4)]
    if min(sides) < 12 or max(sides) / max(min(sides), 1) > 6:
        return False
    eh, ew = exemplar_shape
    exemplar_ar = ew / eh
    box = quad_to_box(quad, scene_shape)
    if box[3] == 0:
        return False
    found_ar = box[2] / box[3]
    return 0.4 < found_ar / exemplar_ar < 2.5


def detect_posters(gray, exemplars, max_instances=8, min_inliers=9):
    """Find every instance of every reference crop in the scene.

    The posters are identical printed artwork repeated along a street, so after
    each successful match the inlier keypoints are struck out and the match is
    run again -- that is what turns a single-best-match matcher into a
    multi-instance one.
    """
    orb = cv2.ORB_create(nfeatures=SCENE_FEATURES)
    kp, des = orb.detectAndCompute(gray, None)
    if des is None or len(kp) < 30:
        return []

    matcher = cv2.BFMatcher(cv2.NORM_HAMMING)
    available = np.ones(len(kp), dtype=bool)
    found = []

    for ex in exemplars:
        for _ in range(max_instances):
            idx_map = np.flatnonzero(available)
            if len(idx_map) < 30:
                break
            pairs = matcher.knnMatch(ex["des"], des[idx_map], k=2)
            good = [q[0] for q in pairs if len(q) == 2 and q[0].distance < RATIO * q[1].distance]
            if len(good) < min_inliers + 3:
                break

            src = np.float32([ex["kp"][m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
            dst = np.float32([kp[idx_map[m.trainIdx]].pt for m in good]).reshape(-1, 1, 2)
            H, mask = cv2.findHomography(src, dst, cv2.RANSAC, 6.0)
            if H is None:
                break
            inliers = mask.ravel().astype(bool)
            if inliers.sum() < min_inliers:
                break

            consumed = [idx_map[m.trainIdx] for m, ok in zip(good, inliers) if ok]
            available[consumed] = False

            eh, ew = ex["shape"]
            corners = np.float32([[0, 0], [ew, 0], [ew, eh], [0, eh]]).reshape(-1, 1, 2)
            quad = cv2.perspectiveTransform(corners, H).reshape(-1, 2)
            if not sane_quad(quad, ex["shape"], gray.shape):
                continue

            found.append({
                "label": ex["label"],
                "exemplar": ex["name"],
                "inliers": int(inliers.sum()),
                "quad": quad.tolist(),
                "box": quad_to_box(quad, gray.shape),
            })

    boxes = [f["box"] for f in found]
    scores = [f["inliers"] for f in found]
    return [found[i] for i in nms(boxes, scores, thr=0.45)]


# --------------------------------------------------------------------------- faces

def detect_faces(img, scales, score_thr=0.55):
    if not YUNET.exists():
        print(f"no face model at {YUNET}; skipping faces", file=sys.stderr)
        return []
    h, w = img.shape[:2]
    det = cv2.FaceDetectorYN.create(str(YUNET), "", (w, h), score_thr, 0.3, 5000)
    boxes, scores = [], []
    for s in scales:
        scaled = img if s == 1.0 else cv2.resize(img, None, fx=s, fy=s, interpolation=cv2.INTER_LINEAR)
        sh, sw = scaled.shape[:2]
        det.setInputSize((sw, sh))
        _, faces = det.detect(scaled)
        if faces is None:
            continue
        for f in faces:
            x, y, fw, fh = (f[:4] / s).tolist()
            boxes.append([int(x), int(y), int(fw), int(fh)])
            scores.append(float(f[-1]))
    return [{"box": boxes[i], "score": round(scores[i], 3)} for i in nms(boxes, scores, thr=0.3)]


# --------------------------------------------------------------------------- plates

def detect_plates(img):
    """Israeli plates are yellow with black glyphs and a ~4.3:1 aspect ratio.

    Colour plus shape is enough here and needs no model. The aspect filter is
    what keeps it off the yellow Yechi stickers, which are portrait.
    """
    h, w = img.shape[:2]
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, (15, 90, 90), (38, 255, 255))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 9), np.uint8))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    out = []
    for c in contours:
        x, y, cw, ch = cv2.boundingRect(c)
        if cw < 24 or ch < 7 or cw * ch > 0.03 * w * h:
            continue
        if not 2.2 <= cw / ch <= 6.5:
            continue
        if cv2.contourArea(c) / (cw * ch) < 0.55:
            continue
        patch = cv2.cvtColor(img[y:y + ch, x:x + cw], cv2.COLOR_BGR2GRAY)
        dark = float((patch < 90).mean())
        if not 0.04 <= dark <= 0.55:
            continue
        out.append({"box": [x, y, cw, ch], "dark_ratio": round(dark, 3)})
    return out


# --------------------------------------------------------------------------- output

def pixelate(img, boxes, blocks=9, pad=0.18):
    h, w = img.shape[:2]
    for x, y, bw, bh in boxes:
        px, py = int(bw * pad), int(bh * pad)
        x0, y0 = max(0, x - px), max(0, y - py)
        x1, y1 = min(w, x + bw + px), min(h, y + bh + py)
        if x1 - x0 < 4 or y1 - y0 < 4:
            continue
        region = img[y0:y1, x0:x1]
        small = cv2.resize(region, (blocks, blocks), interpolation=cv2.INTER_LINEAR)
        img[y0:y1, x0:x1] = cv2.resize(small, (x1 - x0, y1 - y0), interpolation=cv2.INTER_NEAREST)
    return img


def annotate(img, posters, faces, plates):
    out = img.copy()
    for p in posters:
        quad = np.array(p["quad"], dtype=np.int32).reshape(-1, 1, 2)
        colour = BOX_COLOUR.get(p["label"], (255, 255, 255))
        cv2.polylines(out, [quad], True, colour, 6, cv2.LINE_AA)
        x, y = p["box"][0], max(30, p["box"][1] - 10)
        cv2.putText(out, f'{p["label"]} {p["inliers"]}', (x, y),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.1, colour, 3, cv2.LINE_AA)
    for f in faces:
        x, y, bw, bh = f["box"]
        cv2.rectangle(out, (x, y), (x + bw, y + bh), (255, 120, 0), 3)
    for p in plates:
        x, y, bw, bh = p["box"]
        cv2.rectangle(out, (x, y), (x + bw, y + bh), (0, 0, 255), 3)
    return out


def labelme_json(image_path, shape, posters):
    """Pre-labels for hand correction in labelme. Correcting beats drawing."""
    return {
        "version": "5.5.0",
        "flags": {},
        "shapes": [
            {
                "label": p["label"],
                "points": [[float(p["box"][0]), float(p["box"][1])],
                           [float(p["box"][0] + p["box"][2]), float(p["box"][1] + p["box"][3])]],
                "group_id": None,
                "description": f'auto: {p["exemplar"]} ({p["inliers"]} inliers)',
                "shape_type": "rectangle",
                "flags": {},
            }
            for p in posters
        ],
        "imagePath": image_path.name,
        "imageData": None,
        "imageHeight": shape[0],
        "imageWidth": shape[1],
    }


def copy_exif(src, dst):
    if not shutil.which("exiftool"):
        return
    subprocess.run(
        ["exiftool", "-q", "-tagsFromFile", str(src), "-all:all",
         "-overwrite_original", str(dst)],
        check=False,
    )


# --------------------------------------------------------------------------- driver

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder", type=Path, help="batch folder, e.g. photos/rebbe-posters/3108")
    ap.add_argument("--no-faces", action="store_true")
    ap.add_argument("--no-plates", action="store_true")
    ap.add_argument("--no-posters", action="store_true")
    ap.add_argument("--face-scales", default="1.0,2.0",
                    help="comma-separated scales; 2.0 catches small distant faces at ~4x cost")
    ap.add_argument("--annotated-width", type=int, default=1280)
    args = ap.parse_args()

    args.folder = args.folder.resolve()
    if not args.folder.is_dir():
        sys.exit(f"not a directory: {args.folder}")

    scales = [float(s) for s in args.face_scales.split(",") if s.strip()]
    exemplars = [] if args.no_posters else load_exemplars(EXEMPLAR_DIR)
    if not args.no_posters and not exemplars:
        print(f"no usable reference crops in {EXEMPLAR_DIR}", file=sys.stderr)

    project, batch = args.folder.parts[-2], args.folder.parts[-1]
    out_root = REPO / "derived" / project / batch
    (out_root / "redacted").mkdir(parents=True, exist_ok=True)
    (out_root / "annotated").mkdir(parents=True, exist_ok=True)
    label_dir = REPO / "labels" / project / batch
    auto_dir = label_dir / "auto"
    auto_dir.mkdir(parents=True, exist_ok=True)

    photos = sorted(p for p in args.folder.iterdir() if p.suffix.lower() in IMAGE_SUFFIXES)
    manifest = []

    for path in photos:
        img = cv2.imread(str(path))
        if img is None:
            print(f"unreadable: {path.name}", file=sys.stderr)
            continue
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        posters = detect_posters(gray, exemplars) if exemplars else []
        faces = [] if args.no_faces else detect_faces(img, scales)
        plates = [] if args.no_plates else detect_plates(img)

        # The campaign artwork is the subject of the survey and carries a face of
        # its own. Redacting it would destroy the evidence, so every protected
        # region vetoes any face or plate box sitting inside it. Auto detections
        # only find about half the posters, so hand-corrected labels count too.
        corrected = load_corrected_labels(label_dir, path.stem)
        protected = [p["box"] for p in posters] + [c["box"] for c in corrected]
        kept_faces = [f for f in faces if all(containment(f["box"], b) < 0.5 for b in protected)]
        kept_plates = [p for p in plates if all(containment(p["box"], b) < 0.5 for b in protected)]
        spared = (len(faces) - len(kept_faces)) + (len(plates) - len(kept_plates))
        faces, plates = kept_faces, kept_plates

        redacted = pixelate(img.copy(), [f["box"] for f in faces] + [p["box"] for p in plates])
        red_path = out_root / "redacted" / path.name
        cv2.imwrite(str(red_path), redacted, [cv2.IMWRITE_JPEG_QUALITY, 92])
        copy_exif(path, red_path)

        marked = annotate(redacted, posters, faces, plates)
        scale = args.annotated_width / marked.shape[1]
        if scale < 1:
            marked = cv2.resize(marked, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        cv2.imwrite(str(out_root / "annotated" / path.name), marked, [cv2.IMWRITE_JPEG_QUALITY, 80])

        (auto_dir / f"{path.stem}.json").write_text(
            json.dumps(labelme_json(path, img.shape, posters), indent=2), encoding="utf-8")

        counts = {c: sum(1 for p in posters if p["label"] == c) for c in CLASSES}
        manifest.append({
            "photo": str(path.relative_to(REPO)),
            "redacted": str(red_path.relative_to(REPO)),
            "counts": counts,
            "posters": posters,
            "faces": faces,
            "plates": plates,
            "protected_regions": len(protected),
            "redactions_vetoed": spared,
        })
        print(f'{path.name}: {counts["poster"]} poster, {counts["sticker"]} sticker, '
              f"{len(faces)} face, {len(plates)} plate"
              + (f", {spared} redaction vetoed on artwork" if spared else ""))

    (out_root / "detections.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"\n{len(manifest)} images -> {out_root}")
    print(f"auto pre-labels -> {auto_dir}")
    print(f"correct them in labelme and save to {label_dir} to protect missed posters")


if __name__ == "__main__":
    main()
