"""Run scripts/train_detector.py on a Modal GPU and bring the weights home.

The GPU container does the training only. It mounts the same trainer this repo
uses locally -- there is no second copy of the training logic -- pulls the
public dataset from the Hub, and returns the weights and metrics as bytes. The
push to Hugging Face happens on the calling machine with the local token, so no
credential is uploaded to Modal.

Usage:
    modal run --profile danielrosehill scripts/train_modal.py
    modal run --profile danielrosehill scripts/train_modal.py --epochs 400 --imgsz 1280
    modal run --profile danielrosehill scripts/train_modal.py --push danielrosehill/jerusalem-poster-detector

Why this exists: Hugging Face Jobs is the tidier route (`hf jobs uv run`), but
it requires a Pro/Team plan and a token carrying `job.write`. On a free account
it returns 403 `missing permissions: job.write`, which reads like a scope typo
rather than a billing state.
"""

import sys
from pathlib import Path

import modal

REPO = Path(__file__).resolve().parent.parent
TRAINER = REPO / "scripts" / "train_detector.py"

image = (
    modal.Image.debian_slim(python_version="3.12")
    # Ultralytics pulls OpenCV, which needs these at import time and fails with a
    # bare ImportError on libGL.so.1 without them.
    .apt_install("libgl1", "libglib2.0-0")
    .pip_install("ultralytics>=8.3.0", "huggingface-hub>=0.34.0", "pillow")
    .add_local_file(TRAINER, "/root/train_detector.py", copy=True)
)

app = modal.App("jerusalem-poster-detector", image=image)


@app.function(gpu="L4", timeout=60 * 60)
def train(args: list[str]) -> dict:
    import json
    import subprocess

    cmd = [sys.executable, "/root/train_detector.py", "--workdir", "/work", *args]
    print("running:", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True)

    work = Path("/work")
    best = work / "train" / "weights" / "best.pt"
    out = {
        "weights": best.read_bytes(),
        "metrics": json.loads((work / "metrics.json").read_text()),
        "plots": {},
    }
    for plot in ("results.png", "confusion_matrix.png", "PR_curve.png", "val_batch0_pred.jpg"):
        src = work / "train" / plot
        if src.exists():
            out["plots"][plot] = src.read_bytes()
    return out


@app.local_entrypoint()
def main(
    epochs: int = 300,
    imgsz: int = 1280,
    batch: int = 4,
    freeze: int = 10,
    lr0: float = 0.001,
    model: str = "yolo11n.pt",
    dataset: str = "danielrosehill/jerusalem-poster-detection",
    push: str = "",
    private: bool = False,
    all_data: bool = False,
    out: str = "runs/modal",
):
    import json

    args = [
        "--epochs", str(epochs), "--imgsz", str(imgsz), "--batch", str(batch),
        "--freeze", str(freeze), "--lr0", str(lr0), "--model", model, "--dataset", dataset,
    ]
    if all_data:
        args.append("--all-data")
    result = train.remote(args)

    outdir = Path(out)
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "best.pt").write_bytes(result["weights"])
    (outdir / "metrics.json").write_text(json.dumps(result["metrics"], indent=2) + "\n")
    for name, blob in result["plots"].items():
        (outdir / name).write_bytes(blob)

    m = result["metrics"]
    print(f"\nweights -> {outdir / 'best.pt'} ({len(result['weights']) / 1e6:.1f} MB)")
    print(f"mAP@50 {m['map50']:.3f} | mAP@50-95 {m['map50_95']:.3f} "
          f"| P {m['precision']:.3f} | R {m['recall']:.3f}")
    print(f"train {m['train_images']} img / val {m['val_images']} img "
          f"(held out {', '.join(m['val_locations'])})")

    if push:
        sys.path.insert(0, str(REPO / "scripts"))
        import argparse

        import train_detector

        card_args = argparse.Namespace(push=push, dataset=dataset, private=private)
        try:
            from huggingface_hub import HfApi
        except ImportError:
            print(f"\nweights are in {outdir}, but huggingface_hub is missing from the "
                  "environment running `modal run`, so the push was skipped. "
                  "Install it there (uv pip install huggingface-hub modal) and re-run, "
                  "or upload the folder with `hf upload`.")
            return

        api = HfApi()
        api.create_repo(push, repo_type="model", exist_ok=True, private=private)
        (outdir / "README.md").write_text(
            train_detector.model_card(card_args, m, m["classes"]), encoding="utf-8"
        )
        api.upload_folder(folder_path=str(outdir), repo_id=push, repo_type="model")
        print(f"pushed -> https://huggingface.co/{push}")
