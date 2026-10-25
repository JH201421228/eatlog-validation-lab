"""Exercise missing/corrupt local payload recovery with two real public images.

Uses a temporary clone-like directory. Original images and manifests stay intact.
Network downloads are only two frozen, public pilot PNGs; no model calls.
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import shutil
import tempfile
from pathlib import Path

import collect_nutrition5k as collector


def main():
    original_root, original_data = collector.ROOT, collector.DATA
    original_rows = collector.read_jsonl(original_data / "manifest.jsonl")
    pilot = [row for row in original_rows if row["split"] == "pilot"]
    assertions = {}
    with tempfile.TemporaryDirectory(prefix="eatlog-download-resume-") as temporary:
        temporary_root = Path(temporary).resolve()
        if not temporary_root.is_relative_to(Path(tempfile.gettempdir()).resolve()):
            raise ValueError("Temporary cleanup path escaped expected temporary directory")
        try:
            collector.ROOT = temporary_root
            collector.DATA = temporary_root / "data" / "nutrition5k"
            collector.DATA.mkdir(parents=True)
            for name in ("selection_manifest.jsonl", "selection_summary.json"):
                shutil.copy2(original_data / name, collector.DATA / name)
            local_rows = [{**row, "download_status": row["download_status"] if row["split"] == "pilot" else "pending"} for row in original_rows]
            collector.dump_jsonl(collector.DATA / "manifest.jsonl", local_rows)
            for row in pilot:
                path = temporary_root / row["image_path"]
                path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(original_root / row["image_path"], path)
            # Simulate ignored payload absent after clone, and a damaged local cache.
            (temporary_root / pilot[0]["image_path"]).unlink()
            (temporary_root / pilot[1]["image_path"]).write_bytes(b"corrupt local cache")
            with contextlib.redirect_stdout(io.StringIO()):
                collector.download(split="pilot", workers=2)
            restored = {row["sample_id"]: row for row in collector.read_jsonl(collector.DATA / "manifest.jsonl")}
            for index, case in ((0, "missing_payload_recovered"), (1, "corrupt_payload_recovered")):
                row = pilot[index]
                local_hash = hashlib.sha256((temporary_root / row["image_path"]).read_bytes()).hexdigest()
                original_hash = hashlib.sha256((original_root / row["image_path"]).read_bytes()).hexdigest()
                assertions[case] = restored[row["sample_id"]]["download_status"] == "ok" and local_hash == original_hash == row["image_sha256"]
            assertions["all_20_pilot_files_ok"] = all(restored[row["sample_id"]]["download_status"] == "ok" for row in pilot)
        finally:
            collector.ROOT, collector.DATA = original_root, original_data
    result = {"verified_at_utc": collector.utc_now(), "method": "Temporary clone-like directory with frozen manifest, one absent PNG and one corrupted PNG; real official downloads and SHA256 comparison",
        "sample_ids": [row["sample_id"] for row in pilot[:2]], "assertions": assertions,
        "original_data_modified": False, "paid_model_calls": 0, "passed": all(assertions.values())}
    collector.dump_json(original_data / "download_resume_check.json", result)
    print(json.dumps(result, indent=2))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
