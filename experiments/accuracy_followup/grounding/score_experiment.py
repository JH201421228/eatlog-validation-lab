"""Score already frozen predictions; truth is never handed to retrieval."""
from __future__ import annotations

import argparse
import json
import random
import statistics
from datetime import datetime, timezone
from pathlib import Path

from prepare_reference import HERE, LAB, sha, write_json, write_jsonl
from run_experiment import ARMS, read_jsonl


def summary(rows):
    valid = [r for r in rows if r["absolute_error_kcal"] is not None]
    absolute = [r["absolute_error_kcal"] for r in valid]
    ape = [r["absolute_percentage_error"] for r in valid]
    return {
        "selected": len(rows), "valid": len(valid), "failed_or_missing": len(rows) - len(valid),
        "mae_kcal": statistics.fmean(absolute), "mape_pct": 100 * statistics.fmean(ape),
        "wape_pct": 100 * sum(absolute) / sum(r["truth_kcal"] for r in valid),
        "median_ape_pct": 100 * statistics.median(ape),
        "bias_kcal": statistics.fmean(r["prediction_kcal"] - r["truth_kcal"] for r in valid),
        "within_15pct_valid_pct": 100 * sum(v <= .15 for v in ape) / len(valid),
        "within_15pct_selected_pct": 100 * sum(v <= .15 for v in ape) / len(rows),
    }


def comparison(base, revised):
    valid = [(a, b) for a, b in zip(base, revised) if a["absolute_error_kcal"] is not None and b["absolute_error_kcal"] is not None]
    changed = [(a, b) for a, b in valid if abs(a["prediction_kcal"] - b["prediction_kcal"]) > 1e-9]
    diffs = [b["absolute_error_kcal"] - a["absolute_error_kcal"] for a, b in valid]
    rng = random.Random(20261025)
    means = sorted(statistics.fmean(rng.choices(diffs, k=len(diffs))) for _ in range(2000))
    return {
        "paired_valid": len(valid), "changed_kcal_predictions": len(changed),
        "improved": sum(b["absolute_error_kcal"] < a["absolute_error_kcal"] - 1e-9 for a, b in changed),
        "worsened": sum(b["absolute_error_kcal"] > a["absolute_error_kcal"] + 1e-9 for a, b in changed),
        "unchanged_error_among_changed": sum(abs(b["absolute_error_kcal"] - a["absolute_error_kcal"]) <= 1e-9 for a, b in changed),
        "mae_delta_revised_minus_base_kcal": statistics.fmean(diffs),
        "paired_bootstrap_95pct_mae_delta": [means[49], means[1949]],
        "bootstrap_replicates": 2000, "bootstrap_seed": 20261025,
        "interpretation": "exploratory paired dish resampling; not a confirmatory significance claim",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", type=Path, default=HERE / "results")
    parser.add_argument("--manifest", type=Path, default=LAB / "data/nutrition5k/selection_manifest_v3.jsonl")
    args = parser.parse_args()
    freeze = json.loads((args.results / "prediction_freeze.json").read_text(encoding="utf-8"))
    for name, expected in freeze["code_sha256"].items():
        assert sha(HERE / name) == expected, f"Implementation changed after freeze: {name}"
    for arm, expected in freeze["prediction_sha256"].items():
        assert sha(args.results / f"{arm}.jsonl") == expected, f"Prediction changed after freeze: {arm}"
    # Only total kcal and aggregation strata are projected. No ingredient field is consumed.
    truth = {r["sample_id"]: {"kcal": r["truth"]["calories_kcal"], "view": r["camera_view"], "original_split": r["original_split"]}
             for r in read_jsonl(args.manifest) if r["split"] == "blind_test"}
    scored = {}
    reports = {}
    for arm in ARMS:
        rows = read_jsonl(args.results / f"{arm}.jsonl")
        assert set(truth) == {r["sample_id"] for r in rows}, "Membership mismatch"
        results = []
        for row in rows:
            target = truth[row["sample_id"]]
            prediction = row["totals"]["calories"] if row["status"] == "success" else None
            absolute = abs(prediction - target["kcal"]) if prediction is not None else None
            results.append({
                "sample_id": row["sample_id"], "arm": arm, "status": row["status"],
                "truth_kcal": target["kcal"], "prediction_kcal": prediction,
                "absolute_error_kcal": absolute, "absolute_percentage_error": absolute / target["kcal"] if absolute is not None else None,
                "db_food_groups": sum(s["source"] == "db" for s in row.get("selected", [])),
                "view": target["view"], "original_split": target["original_split"],
            })
        scored[arm] = results
        reports[arm] = {"overall": summary(results),
                        "by_view": {view: summary([r for r in results if r["view"] == view]) for view in sorted({r["view"] for r in results})},
                        "by_original_split": {s: summary([r for r in results if r["original_split"] == s]) for s in ("train", "test")}}
        write_jsonl(args.results / f"{arm}_scored.jsonl", results)
    comparisons = {f"{arm}_vs_{base}": comparison(scored[base], scored[arm])
                   for base in ("no_db", "current_exact") for arm in ARMS if arm not in {base, "no_db"}}
    report = {
        "scored_at_utc": datetime.now(timezone.utc).isoformat(), "evaluation_kind": "exploratory_existing_1000",
        "manifest_sha256": sha(args.manifest), "prediction_freeze_sha256": sha(args.results / "prediction_freeze.json"),
        "production_db_snapshot": False, "thresholds_tuned_to_truth": False,
        "arms": reports, "comparisons": comparisons,
    }
    write_json(args.results / "score_summary.json", report)
    print(json.dumps({"overall": {arm: r["overall"] for arm, r in reports.items()}, "comparisons": comparisons}, ensure_ascii=False))


if __name__ == "__main__":
    main()
