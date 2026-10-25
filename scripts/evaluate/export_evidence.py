"""Publish an allowlisted, reproducible response archive for public food images.

This is not the SDK response object, HTTP trace, headers, key, or image archive.
Only fields the collector itself constructed from model text/usage are retained.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from common import ROOT, EVAL, atomic_json, read_json, read_jsonl, sample_id, sha256, utc_now, write_jsonl

ALLOWED = (
    "sample_id", "split", "started_at", "completed_at", "status", "raw_text", "usage",
    "finish_reason", "model_version", "json_object_valid", "latency_ms", "image_sha256",
    "request_sha256", "request_config_sha256", "selection_manifest_sha256",
    "counted_input_tokens", "input_upper_bound_tokens", "token_bound_violation",
    "error_type", "error_code",
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    selected = {sample_id(row) for row in read_jsonl(args.manifest)}
    rows = []
    for path in sorted((EVAL / "raw_responses").glob("*.json")):
        original = read_json(path)
        record = {key: original[key] for key in ALLOWED if key in original}
        record["included_in_active_manifest"] = record["sample_id"] in selected
        record["original_record_sha256"] = sha256(path.read_bytes())
        rows.append(record)
    target = EVAL / "evidence/model_responses.jsonl"
    write_jsonl(target, rows)
    atomic_json(EVAL / "evidence/archive_manifest.json", {
        "created_at": utc_now(), "source": "Actual Gemini calls on public Nutrition5k food images",
        "manifest_sha256": sha256(args.manifest.read_bytes()), "records": len(rows),
        "included_in_active_manifest": sum(r["included_in_active_manifest"] for r in rows),
        "excluded_metadata_qc_records": sum(not r["included_in_active_manifest"] for r in rows),
        "archive_sha256": sha256(target.read_bytes()), "allowlisted_fields": list(ALLOWED),
        "contains_original_images": False, "contains_http_headers_or_credentials": False,
        "replay_note": "raw_text can be replayed through pinned AI and BE snapshots without another paid model call",
    })
    print({"exported": len(rows), "included": sum(r["included_in_active_manifest"] for r in rows), "archive": str(target.relative_to(ROOT))})


if __name__ == "__main__":
    main()
