"""
Grounding DINO zero-shot detection on SVS plumbing images.

Usage:
    python scripts/gdino_detect.py \
        --project svs_plumbing \
        --prompt "leak . pipe . valve ." \
        --threshold 0.3 \
        --limit 20          # omit to run on all images

Output:
    projects/<project>/experiments/gdino_<run>/
        detections.json     — all boxes + scores + labels
        annotated/          — images with drawn boxes
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


# ── colour palette per label ─────────────────────────────────────────────────
PALETTE = {
    "leak":  "#E74C3C",
    "pipe":  "#3498DB",
    "valve": "#2ECC71",
}
DEFAULT_COLOR = "#F39C12"


def get_color(label: str) -> str:
    for key, color in PALETTE.items():
        if key in label.lower():
            return color
    return DEFAULT_COLOR


# ── drawing ───────────────────────────────────────────────────────────────────
def draw_boxes(image: Image.Image, boxes, scores, labels) -> Image.Image:
    img = image.copy().convert("RGB")
    draw = ImageDraw.Draw(img)
    W, H = img.size

    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 16)
    except Exception:
        font = ImageFont.load_default()

    for box, score, label in zip(boxes, scores, labels):
        # box is [cx, cy, w, h] normalised → convert to pixel xyxy
        cx, cy, bw, bh = box
        x1 = int((cx - bw / 2) * W)
        y1 = int((cy - bh / 2) * H)
        x2 = int((cx + bw / 2) * W)
        y2 = int((cy + bh / 2) * H)

        color = get_color(label)
        draw.rectangle([x1, y1, x2, y2], outline=color, width=3)
        text = f"{label} {score:.2f}"
        draw.rectangle([x1, y1 - 20, x1 + len(text) * 9, y1], fill=color)
        draw.text((x1 + 2, y1 - 18), text, fill="white", font=font)

    return img


# ── main ──────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project",   default="svs_plumbing")
    parser.add_argument("--prompt",    default="leak . pipe . valve .")
    parser.add_argument("--threshold", type=float, default=0.3)
    parser.add_argument("--limit",     type=int,   default=0,
                        help="Max images to process (0 = all)")
    parser.add_argument("--model",     default="IDEA-Research/grounding-dino-tiny",
                        help="HF model ID")
    args = parser.parse_args()

    # ── lazy imports so the script is importable without deps ─────────────────
    try:
        import torch
        from transformers import AutoProcessor, AutoModelForZeroShotObjectDetection
    except ImportError:
        sys.exit(
            "Missing dependencies. Run:\n"
            "  pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu\n"
            "  pip install transformers"
        )

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Device: {device}")
    print(f"Prompt: {args.prompt!r}  |  threshold: {args.threshold}")

    # ── load model ─────────────────────────────────────────────────────────────
    print(f"Loading {args.model} …")
    processor = AutoProcessor.from_pretrained(args.model)
    model     = AutoModelForZeroShotObjectDetection.from_pretrained(args.model).to(device)
    model.eval()

    # ── image paths ────────────────────────────────────────────────────────────
    raw_dir = Path("projects") / args.project / "datasets" / "raw"
    if not raw_dir.exists():
        sys.exit(f"Raw dataset not found: {raw_dir}")

    image_paths = sorted(raw_dir.glob("*.jpg"))
    if args.limit:
        image_paths = image_paths[: args.limit]
    print(f"Processing {len(image_paths)} images …\n")

    # ── output dirs ────────────────────────────────────────────────────────────
    run_name  = f"gdino_{int(time.time())}"
    out_dir   = Path("projects") / args.project / "experiments" / run_name
    ann_dir   = out_dir / "annotated"
    ann_dir.mkdir(parents=True, exist_ok=True)

    all_detections = []

    # ── inference loop ─────────────────────────────────────────────────────────
    for idx, img_path in enumerate(image_paths, 1):
        image = Image.open(img_path).convert("RGB")

        inputs = processor(
            images=image,
            text=args.prompt,
            return_tensors="pt"
        ).to(device)

        with torch.no_grad():
            outputs = model(**inputs)

        results = processor.post_process_grounded_object_detection(
            outputs,
            inputs.input_ids,
            box_threshold=args.threshold,
            text_threshold=args.threshold,
            target_sizes=[image.size[::-1]],   # (H, W)
        )[0]

        boxes_xyxy = results["boxes"].cpu().tolist()
        scores     = results["scores"].cpu().tolist()
        labels     = results["labels"]

        # convert xyxy pixels → cxcywh normalised for storage
        W, H = image.size
        boxes_norm = []
        for x1, y1, x2, y2 in boxes_xyxy:
            cx = ((x1 + x2) / 2) / W
            cy = ((y1 + y2) / 2) / H
            bw = (x2 - x1) / W
            bh = (y2 - y1) / H
            boxes_norm.append([cx, cy, bw, bh])

        det = {
            "image": img_path.name,
            "detections": [
                {"label": lbl, "score": round(sc, 4), "box_cxcywh_norm": box}
                for lbl, sc, box in zip(labels, scores, boxes_norm)
            ],
        }
        all_detections.append(det)

        n = len(scores)
        status = f"[{idx}/{len(image_paths)}] {img_path.name} → {n} detection(s)"
        if n:
            status += "  " + ", ".join(f"{l}({s:.2f})" for l, s in zip(labels, scores))
        print(status)

        # draw & save
        annotated = draw_boxes(image, boxes_norm, scores, labels)
        annotated.save(ann_dir / img_path.name)

    # ── save detections JSON ───────────────────────────────────────────────────
    json_path = out_dir / "detections.json"
    with open(json_path, "w") as f:
        json.dump(
            {
                "model": args.model,
                "prompt": args.prompt,
                "threshold": args.threshold,
                "results": all_detections,
            },
            f,
            indent=2,
        )

    # ── summary ────────────────────────────────────────────────────────────────
    total_dets = sum(len(d["detections"]) for d in all_detections)
    images_with_hits = sum(1 for d in all_detections if d["detections"])
    label_counts: dict[str, int] = {}
    for d in all_detections:
        for det in d["detections"]:
            label_counts[det["label"]] = label_counts.get(det["label"], 0) + 1

    print(f"\n{'─'*50}")
    print(f"Run:           {run_name}")
    print(f"Images:        {len(all_detections)}")
    print(f"With hits:     {images_with_hits}")
    print(f"Total dets:    {total_dets}")
    for lbl, cnt in sorted(label_counts.items()):
        print(f"  {lbl:>12}: {cnt}")
    print(f"JSON saved:    {json_path}")
    print(f"Annotated:     {ann_dir}")


if __name__ == "__main__":
    main()
