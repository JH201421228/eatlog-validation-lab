"""Check every requested image against verified final dataset checksums."""
from __future__ import annotations

import argparse
from pathlib import Path

from common import ROOT, EVAL, atomic_json, image_path, read_json, read_jsonl, sample_id, sha256, utc_now


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--download-manifest", type=Path, default=ROOT / "data/nutrition5k/manifest.jsonl")
    args = parser.parse_args()
    selection = {sample_id(row): row for row in read_jsonl(args.manifest)}
    downloads = {sample_id(row): row for row in read_jsonl(args.download_manifest)}
    failures, checks = [], []
    excluded = 0
    for rawpath in sorted((EVAL / "raw_responses").glob("*.json")):
        raw = read_json(rawpath)
        if "latency_ms" not in raw:
            continue
        identifier = raw["sample_id"]
        if identifier not in selection:
            excluded += 1
            # These are pilot calls excluded by metadata QA; still check actual bytes.
            path = ROOT / "data/nutrition5k/images" / f"{identifier}.png"
            actual = sha256(path.read_bytes()) if path.exists() else None
            check = {"sample_id": identifier, "included": False,
                     "matches_actual_file": actual == raw.get("image_sha256")}
        else:
            row = downloads.get(identifier, {})
            path = image_path(selection[identifier])
            actual = sha256(path.read_bytes()) if path.exists() else None
            check = {"sample_id": identifier, "included": True,
                     "download_verified": row.get("download_status") == "ok",
                     "matches_verified_download_sha256": raw.get("image_sha256") == row.get("image_sha256") == actual,
                     "matches_selected_image_path": row.get("image_path") == selection[identifier]["image_path"]}
        checks.append(check)
        if any(value is False for key, value in check.items() if key not in {"included"}):
            failures.append(check)
    result = {"checked_at": utc_now(), "manifest_sha256": sha256(args.manifest.read_bytes()),
              "download_manifest_sha256": sha256(args.download_manifest.read_bytes()),
              "requested_images_checked": len(checks), "excluded_pilot_images_checked": excluded,
              "failure_count": len(failures), "failures": failures, "checks": checks}
    atomic_json(EVAL / "evidence/image_request_audit.json", result)
    print({"checked": len(checks), "excluded": excluded, "failures": len(failures)})
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
