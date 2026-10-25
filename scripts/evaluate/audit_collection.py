"""Inspect transport/usage without reading nutrition ground truth."""
from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

from common import EVAL, atomic_json, read_json, read_jsonl, sample_id, utc_now
from metrics import percentile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=["pilot", "blind_test"], required=True)
    parser.add_argument("--manifest", type=Path)
    args = parser.parse_args()
    rows = [read_json(path) for path in sorted((EVAL / "raw_responses").glob("*.json"))]
    rows = [row for row in rows if row["split"] == args.split]
    all_stored = len(rows)
    if args.manifest:
        selected_ids = {sample_id(row) for row in read_jsonl(args.manifest) if row["split"] == args.split}
        rows = [row for row in rows if row["sample_id"] in selected_ids]
    usage = [r["usage"] for r in rows if r.get("usage")]
    times = [r["latency_ms"] for r in rows if "latency_ms" in r]
    result = {
        "generated_at": utc_now(), "split": args.split, "ground_truth_read": False,
        "stored_records": len(rows), "status_counts": dict(Counter(r["status"] for r in rows)),
        "excluded_stored_records": all_stored - len(rows),
        "valid_json_objects": sum(r.get("json_object_valid") is True for r in rows),
        "model_versions": dict(Counter(r.get("model_version", "unknown") for r in rows)),
        "finish_reasons": dict(Counter(r.get("finish_reason", "unknown") for r in rows)),
        "usage_tokens": {key: {"sum": sum(u.get(key) or 0 for u in usage),
                               "min": min((u.get(key) or 0 for u in usage), default=None),
                               "max": max((u.get(key) or 0 for u in usage), default=None)}
                         for key in ("prompt_token_count", "candidates_token_count", "thoughts_token_count")},
        "latency_ms": {"p50": percentile(times, .5), "p95": percentile(times, .95)},
        "cost_all_splits": read_json(EVAL / "cost_summary.json"),
        "request_config": read_json(EVAL / "request_config.json"),
    }
    atomic_json(EVAL / "results" / f"{args.split}_transport_summary.json", result)
    print({"split": args.split, "records": len(rows), "json_valid": result["valid_json_objects"], "latency_ms": result["latency_ms"]})


if __name__ == "__main__":
    main()
