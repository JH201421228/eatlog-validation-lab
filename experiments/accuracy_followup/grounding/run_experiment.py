"""Replay frozen model candidates with three DB policies; this never loads truth."""
from __future__ import annotations

import argparse
import json
import logging
import math
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from grounding import Reference, NUTRIENTS
from prepare_reference import HERE, LAB, sha, write_json, write_jsonl

ARMS = ("no_db", "current_exact", "quality_exact", "state_aware")


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def replay(rows, reference, arm):
    from app.ai_client.base import AICandidate
    from app.services.analyze import _grouped_candidates, resolve_nutrition
    output = []
    for row in rows:
        result = {"sample_id": row["sample_id"], "ai_status": row["status"], "arm": arm}
        if row["status"] != "success":
            result.update(status="failed", reason=row.get("reason", row.get("collection_status", "ai_failed")))
            output.append(result)
            continue
        candidates = [AICandidate.model_validate(c) for c in row["candidates"]]
        groups = {}
        for key, candidate in _grouped_candidates(candidates):
            groups.setdefault(key, []).append(candidate)
        picked = [max(group, key=lambda c: c.confidence) for group in groups.values()]
        totals = dict.fromkeys(NUTRIENTS, 0.0)
        mass = 0.0
        details = []
        complete = bool(picked)
        for candidate in picked:
            matched, trace = (None, {"reason": "no_db"}) if arm == "no_db" else reference.match(candidate, arm)
            resolved = resolve_nutrition(candidate, matched)
            nutrition = resolved.nutrition
            if nutrition is None:
                complete = False
            else:
                for key in NUTRIENTS:
                    amount = getattr(nutrition, key) * resolved.estimated_serving
                    if not math.isfinite(amount) or amount < 0:
                        complete = False
                    else:
                        totals[key] += amount
            if resolved.grams is not None:
                mass += resolved.grams
            details.append({
                "food_name": candidate.food_name, "confidence": candidate.confidence,
                "grams": resolved.grams, "count": resolved.count, "count_unit": resolved.count_unit,
                "source": resolved.source, "matched_external_id": getattr(matched, "external_id", None),
                "density_per_100g": resolved.per_100g, "estimated_serving": resolved.estimated_serving,
                "nutrition_per_unit": nutrition.model_dump() if nutrition else None,
                "retrieval": trace,
            })
        result.update(status="success" if complete else "incomplete_nutrition", selected=details,
                      food_groups=len(picked), alternative_groups=sum(len(g) > 1 for g in groups.values()),
                      totals={**totals, "mass_g": mass} if complete else None)
        output.append(result)
    return output


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--be", type=Path, default=LAB.parent / "BE")
    parser.add_argument("--input", type=Path, default=LAB / "evaluation/tmp/replay_blind_test_no_db/improved_ai.jsonl")
    parser.add_argument("--baseline", type=Path, default=LAB / "evaluation/results/blind_test_improved_no_db.jsonl")
    parser.add_argument("--output", type=Path, default=HERE / "results")
    args = parser.parse_args()
    os.environ["DATABASE_URL"] = "sqlite://"
    os.environ["GEMINI_API_KEY"] = ""
    os.environ["COUNT_HALF_STEPS"] = "false"
    logging.disable(logging.CRITICAL)
    sys.path.insert(0, str(args.be.resolve()))
    from app.services.matching import normalize_name, _match_priority
    reference = Reference(read_jsonl(HERE / "reference.jsonl"), normalize_name, _match_priority)
    rows = read_jsonl(args.input)
    assert len({r["sample_id"] for r in rows}) == len(rows), "Duplicate input ids"
    args.output.mkdir(parents=True, exist_ok=True)
    results = {arm: replay(rows, reference, arm) for arm in ARMS}
    original = {r["sample_id"]: r for r in read_jsonl(args.baseline)}
    baseline_mismatches = [r["sample_id"] for r in results["no_db"]
                           if r["sample_id"] not in original or r["status"] != original[r["sample_id"]]["status"]
                           or r.get("totals") != original[r["sample_id"]].get("totals")]
    assert not baseline_mismatches, f"No-DB production replay mismatch: {baseline_mismatches[:10]}"
    structural_mismatches = []
    for arm, predictions in results.items():
        for base, pred in zip(results["no_db"], predictions):
            fields = lambda r: [(s["food_name"], s["confidence"], s["grams"], s["count"], s["count_unit"])
                                for s in r.get("selected", [])]
            if fields(base) != fields(pred):
                structural_mismatches.append({"arm": arm, "sample_id": pred["sample_id"]})
        write_jsonl(args.output / f"{arm}.jsonl", predictions)
    assert not structural_mismatches, "Grounding changed food selection or amount"
    coverage = {}
    for arm, predictions in results.items():
        selected = [s for r in predictions for s in r.get("selected", [])]
        coverage[arm] = {
            "rows": len(predictions), "valid_nutrition": sum(r["status"] == "success" for r in predictions),
            "status_counts": dict(Counter(r["status"] for r in predictions)), "food_groups": len(selected),
            "alternative_groups": sum(r.get("alternative_groups", 0) for r in predictions),
            "matched_food_groups": sum(s["matched_external_id"] is not None for s in selected),
            "db_nutrition_food_groups": sum(s["source"] == "db" for s in selected),
            "dishes_with_db": sum(any(s["source"] == "db" for s in r.get("selected", [])) for r in predictions),
            "fallback_reason_counts": dict(Counter(s["retrieval"]["reason"] for s in selected)),
            "same_name_ambiguity_food_groups": sum(s["retrieval"].get("same_name_rows", 0) > 1 for s in selected),
        }
    write_json(args.output / "coverage.json", coverage)
    freeze = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(), "truth_read_by_prediction_script": False,
        "input_path": str(args.input.resolve().relative_to(LAB)).replace('\\', '/'),
        "input_sha256": sha(args.input), "reference_sha256": sha(HERE / "reference.jsonl"),
        "baseline_comparison_sha256": sha(args.baseline), "baseline_totals_mismatches": baseline_mismatches,
        "selection_or_mass_mismatches": structural_mismatches, "rows": len(rows),
        "code_sha256": {p.name: sha(p) for p in [HERE / "grounding.py", HERE / "run_experiment.py", HERE / "PROTOCOL.md"]},
        "prediction_sha256": {arm: sha(args.output / f"{arm}.jsonl") for arm in ARMS},
        "app_sha256": {p: sha(args.be / p) for p in ["app/services/analyze.py", "app/services/matching.py", "app/ai_client/base.py"]},
    }
    write_json(args.output / "prediction_freeze.json", freeze)
    print(json.dumps(coverage, ensure_ascii=False))


if __name__ == "__main__":
    main()
