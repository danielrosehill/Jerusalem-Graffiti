# Annotating posters and building the training dataset

How a batch of photographs becomes a public object-detection dataset. Two
steps: draw boxes in labelme, then run one script.

Verified 2026-09-01 with labelme 7.2.0 (Python 3.13, installed via
`uv tool install labelme`) on Ubuntu/Wayland.

## The chain

```
photos/<project>/<DDMM>/*.jpg
  + posters.csv                       (survey metadata, already built)
  + annotations/labelme/<project>/<DDMM>/*.json   (boxes, drawn by hand)
  -> dataset/                         (Hugging Face imagefolder + YOLO tree)
```

`annotations/labelme/` is source data and is committed. `dataset/` is a build
artifact — it contains *copies* of the photographs — and is git-ignored. The
published copy lives on the Hugging Face Hub; rebuild it, never hand-edit it.

## 1. Draw the boxes

```bash
labelme "photos/rebbe-posters/3108" \
  --labels annotations/labels.txt \
  --output annotations/labelme/rebbe-posters/3108 \
  --validate-label exact
```

![labelme with a poster boxed on a lamppost](images/labelme-annotation.png)

*Frame `17.30.12`, one sticker boxed. The Timemark watermark burnt into the
photograph carries the same coordinates that `posters.csv` reads out of EXIF —
useful as a visual cross-check, but the CSV never transcribes them off the
pixels.*

`--output` keeps the JSON out of `photos/`, so the photo folders stay exactly
as they came off the phone. `--validate-label exact` refuses any label not in
`annotations/labels.txt`, which is the whole reason a typo cannot quietly
create a second class.

Autosave is **on by default** (`auto_save: true` in labelme's
`_config/default_config.yaml`, not overridden in `~/.labelmerc`) — there is no
save step, and closing the window loses nothing.

In the window: `Ctrl+R` switches to rectangle mode and stays there for the
session; `D` and `A` move between images; `Ctrl+Z` undoes.

Do not pass `--config '{store_data: false}'`. `store_data` is not a valid key
in 7.2.0 and one bad key makes labelme discard the **entire** config string,
silently falling back to defaults. It is unnecessary anyway: 7.2.0 already
leaves `imageData` null unless `--with-image-data` is passed, so the JSON stays
around 3 KB instead of embedding a megabyte of base64 per photograph.

### What counts as a box

One box per visible campaign poster, at its **visible extent** if partly
occluded. The class is `poster` for both physical forms — wheatpaste sheets and
stickers carry the same portrait and slogan, and `posters.csv` already records
which form a frame holds in its `form` column, so splitting the class would
teach a detector scale rather than content.

Leave unboxed: anything too blurred or distant to identify with confidence, and
lookalikes that are not campaign material — memorial notices, election flyers,
the blue-and-white "baruch haba melech hamashiach" sticker of a different
design, plain utility stickers. Those are exactly the false positives a
detector will produce (`docs/vision-pipeline-on-hold.md` records OWLv2 firing
on a memorial notice at 0.967), so they are more useful as unlabelled
background than as a class.

A photograph with **no** JSON is unannotated. A photograph with a JSON and no
shapes is a *verified negative*. `build_dataset.py` treats these differently
and refuses to export the first as the second.

## 2. Build the dataset

```bash
python3 scripts/build_dataset.py --yolo
python3 scripts/build_dataset.py --allow-missing     # export a partial batch
python3 scripts/build_dataset.py --split             # train/validation split
```

It joins the labelme JSON with `posters.csv` on the photo path, renames each
image to its stable survey `id` (`rebbe-posters-3108-171705.jpg` — original
filenames contain spaces and parentheses, which travel badly on the Hub), and
writes `dataset/` with a dataset card, `data/<split>/metadata.jsonl`, and
optionally an Ultralytics `yolo/` tree.

Without `--allow-missing` it **exits non-zero if any photograph in
`posters.csv` lacks a JSON**, and lists them. That is deliberate: exporting an
unannotated photo would enter the dataset as an image with zero boxes, which
teaches a detector that real posters are background.

### Box formats, which are not interchangeable

| Where | Format | Units |
|---|---|---|
| labelme JSON | two corner points `[[x1,y1],[x2,y2]]` | absolute px |
| `metadata.jsonl` | COCO `[x, y, w, h]` | absolute px |
| `yolo/labels/*.txt` | `class cx cy w h` | normalised 0–1 |

Corners are **not** guaranteed ordered in labelme output — a box drawn
bottom-right to top-left stores its points in that order, so `min`/`max` the
coordinates rather than assuming `points[0]` is the top-left. The exporter does
this; anything else reading these files must too.

The exporter also compares `imageWidth`/`imageHeight` in each JSON against the
actual file and exits if they disagree, since that means the photograph was
replaced after annotation and every box in it is wrong.

### Splitting

`--split` groups by `location_id`, never by row. Several frames show the same
lamppost from a few paces apart (`duplicate_of` in `posters.csv` marks the
clearest pair, `17.28.04` and `17.28.13`), so a random per-image split puts
near-identical photographs in both train and validation and reports a score
that is mostly memorisation.

At current volume the default — a single `train` split, with `location_id`
exposed as a column — is the honest option. Let whoever trains on it do grouped
cross-validation.

## 3. Publish to the Hub

`dataset/` is self-contained and uploads as-is:

```bash
hf auth login                                    # once, needs a write token
hf upload-large-folder <user>/<dataset-name> dataset --repo-type=dataset
```

`hf upload <repo> dataset --repo-type=dataset` works too and is simpler for a
folder this small. The dataset card is `dataset/README.md`; its YAML
frontmatter is what makes the Hub show the dataset viewer and the licence tag,
so keep it at the top of the file.

Publishing is public and effectively permanent — the Hub keeps history, and
crawlers cache. Rebuild and re-upload after every annotation change rather than
editing the card on the Hub, or the two copies diverge.

## Scale, honestly

The working threshold for a genuine YOLO11n fine-tune is roughly 50 images and
150+ instances. The 3108 batch is 13 images. Below that, the realistic uses are
few-shot and open-vocabulary detectors (OWLv2 in image-guided mode already
localises these posters — see `docs/vision-pipeline-on-hold.md`), or a
benchmark to measure them against. It is a seed set. More batches make it a
training set.
