"""Decode every selected PNG and audit identical pixels without changing selection.

Requires Pillow. No model calls, image modification, or quality-based replacement.
"""
from __future__ import annotations

import hashlib
from collections import Counter, defaultdict

from PIL import Image, ImageStat, __version__ as pillow_version

from collect_nutrition5k import DATA, ROOT, dump_json, dump_jsonl, read_jsonl, utc_now


def main():
    manifest = read_jsonl(DATA / "manifest.jsonl")
    rows = []
    duplicates = defaultdict(list)
    failures = []
    for sample in manifest:
        path = ROOT / sample["image_path"]
        if sample["download_status"] != "ok":
            failures.append({"sample_id": sample["sample_id"], "reason": "not_downloaded"})
            continue
        try:
            with Image.open(path) as source:
                source.load()
                rgb = source.convert("RGB")
                pixel_hash = hashlib.sha256(rgb.tobytes()).hexdigest()
                extrema = rgb.getextrema()
                stats = ImageStat.Stat(rgb)
                row = {"sample_id": sample["sample_id"], "camera_view": sample["camera_view"],
                    "width": rgb.width, "height": rgb.height, "decoded_mode": "RGB", "pixel_sha256": pixel_hash,
                    "rgb_extrema": extrema, "channel_means": stats.mean,
                    "constant_rgb": all(low == high for low, high in extrema),
                    "near_black_all_channels": max(high for low, high in extrema) <= 8,
                    "selection_changed": False}
                rows.append(row)
                duplicates[(rgb.size, pixel_hash)].append(sample["sample_id"])
        except Exception as error:
            failures.append({"sample_id": sample["sample_id"], "reason": type(error).__name__ + ": " + str(error)})
    dump_jsonl(DATA / "image_pixel_audit.jsonl", rows)
    dump_json(DATA / "image_pixel_audit_summary.json", {"verified_at_utc": utc_now(), "pillow_version": pillow_version,
        "selected_count": len(manifest), "decoded_count": len(rows),
        "unavailable_source_rows": [row for row in failures if row["reason"] == "not_downloaded"],
        "decode_failures": [row for row in failures if row["reason"] != "not_downloaded"],
        "dimensions": dict(Counter(f"{row['width']}x{row['height']}" for row in rows)),
        "constant_rgb_ids": [row["sample_id"] for row in rows if row["constant_rgb"]],
        "near_black_ids": [row["sample_id"] for row in rows if row["near_black_all_channels"]],
        "duplicate_decoded_pixel_groups": [ids for ids in duplicates.values() if len(ids) > 1],
        "selection_changed": False, "interpretation": "Image decode/identity audit only. No frame or sample chosen based on model performance."})
    print(f"Decoded {len(rows)}/{len(manifest)} images; failures={len(failures)}; duplicate_pixel_groups={sum(len(ids) > 1 for ids in duplicates.values())}")


if __name__ == "__main__":
    main()
