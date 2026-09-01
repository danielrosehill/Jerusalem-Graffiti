# Vision pipeline — on hold

**Status: parked 2026-09-01. Not worth the effort at current volume.**

A local computer-vision preprocessing pipeline was built, worked partially, and
was removed. The code is recoverable from git history at commit `f6457d3`. This
file exists so nobody rebuilds it from scratch, or repeats the dead ends.

The decision to park it: photos are published unredacted, which removes the
privacy motivation entirely, and detection accuracy was not good enough to be
worth maintaining for counting alone.

## What it did

Three offline passes over `photos/<project>/<DDMM>/`, writing redacted and
annotated copies to `derived/` and labelme pre-labels to `labels/`:

| Pass | Method | Verdict |
|---|---|---|
| Faces | YuNet, 232 KB ONNX from opencv_zoo, CPU | **Worked well.** 2–10 detections per frame on a busy street |
| Plates | HSV yellow mask + ~4.3:1 aspect (Israeli plates) | Worked; fired on the 2 frames that actually had cars |
| Posters | ORB features + RANSAC homography vs. exemplar crops | **~45% recall.** The reason it was parked |

## Findings worth keeping

**The scene ORB feature budget was the binding constraint, not the matcher.**
At `nfeatures=6000` over a 1920×2560 street scene, *zero* keypoints landed on a
153×208 px sticker — the exemplar failed to match its own source image, which
looks exactly like a broken matcher. At 12000 it produced 14 RANSAC inliers.
Measured, not guessed.

**Lowe ratio test bug.** The comprehension unpacked every `knnMatch` pair as
exactly two elements and length-guarded on `pairs[0]` only, so a single short
candidate list silently zeroed an entire exemplar:

```python
# wrong
good = [m for m, n in pairs if len(pairs[0]) == 2 and m.distance < 0.78 * n.distance]
# right
good = [q[0] for q in pairs if len(q) == 2 and q[0].distance < 0.78 * q[1].distance]
```

**IoU is the wrong test for "is this box inside that box".** The posters carry a
portrait, so YuNet detected the Rebbe's face and the privacy pass pixelated it,
destroying the survey's subject in 3 of 13 frames. The guard meant to prevent
this used IoU — but a face inside a poster scores IoU **0.042** against a 0.2
threshold, so it had never once fired. Use containment (intersection ÷ inner
box area) instead.

**Masking beats vetoing.** Better still than filtering detections afterwards:
find the posters first, flat-fill their pixels, and only then run face
detection. The portrait is never a candidate, so it cannot be scored, boxed or
blurred. Fill the homography **polygon**, not the bounding box — a poster's box
often contains a passer-by standing in front of it whose face should still be
redacted.

**Boxing every face made the review output unreadable.** Draw poster boxes only;
let redaction be silent.

**Colour detection for the yellow stickers half-worked.** HSV `(18,80,80)`–
`(38,255,255)`, portrait aspect 0.45–1.45, fill ≥ 0.38, plus "contains dark
pixels" and "contains blue pixels" to separate real stickers from plain yellow
flags and awnings. It raised detections from 6 to 21 across the batch. But the
boxes were *fragments*: the dark portrait and blue lettering split the yellow
mask, and morphological closing did not fix it — even a 25×25 kernel left the
width at 47 px, because the sticker's shadowed right edge (curving around the
lamppost) fell below the saturation/value floor entirely. Chasing that with
looser bounds is where the effort stopped being worth it.

## The better architecture, if this is ever resumed

Open-vocabulary detection, not feature matching. Tested **OWLv2**
(`google/owlv2-base-patch16-ensemble`) in image-guided mode, querying with the
same exemplar crop:

- Localised the hard sticker in `17.26.18` at score **1.000**, box
  `(842, 898, 114×239)` — **more accurate than a hand measurement**, which had
  clipped the bottom half. ORB missed this sticker entirely.
- 11.4 s per image on CPU, 3 s model load. ~2.5 min for a 13-image batch.
- Failure mode inverts: ORB *misses* things (recall), OWLv2 *over-generalises*
  (precision). At threshold 0.85 it also returned a black memorial notice
  (0.967) and a blue street sign (0.843) — both pole-mounted flyers, neither
  campaign artwork. Precision failures are far cheaper to fix than recall ones.
- Suggested fix, untested: OWLv2 for localisation plus the existing yellow
  colour gate for class confirmation. Neither false positive is yellow.

### OWLv2 API gotchas

Both cost a debugging round trip:

- `post_process_image_guided_detection` needs `target_sizes` as a **tensor**, not
  a list. A list raises `AttributeError: 'list' object has no attribute 'shape'`.
- **OWLv2 pads the input to a square** before resizing, so predictions come back
  in padded space. Post-process against a square of side `max(W, H)`; the image
  then occupies the top-left corner and boxes map 1:1 onto original coordinates.
  Passing the true image size silently returns skewed boxes.
- Requires `scipy`, which is not pulled in by `transformers` and fails only at
  post-processing time, after the model has loaded.

Alternatives not tested: **Grounding DINO** (text-prompted, when no exemplar is
available) and **Florence-2** (detection plus description in one model, which
could fill mounting-surface and condition fields at the same time).

## Annotation tooling

`labelme` was installed (`uv tool install labelme`, Qt6/PySide6, resolves
cleanly on Python 3.12) but no boxes were ever drawn. The pipeline emitted
labelme-format pre-labels so that boxes could be *corrected* rather than drawn
from scratch. If this restarts, that loop is worth keeping: at the time it was
also load-bearing for correctness, because corrected boxes fed the redaction
protection mask, not just the detection record.

Rough threshold for a genuine fine-tune (YOLO11n from COCO weights): ~50 images
/ 150+ instances. This batch has 13 images.
