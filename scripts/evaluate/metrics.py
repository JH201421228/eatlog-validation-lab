"""Failure-aware, paired whole-dish metrics. Run only after inference is frozen."""
from __future__ import annotations

import argparse
import csv
import math
import random
import statistics
from collections import Counter
from pathlib import Path

from common import ROOT, EVAL, atomic_json, image_path, read_json, read_jsonl, sample_id, sha256, utc_now, write_jsonl

MAPPING = {"calories": "calories_kcal", "carbs": "carbs_g", "protein": "protein_g", "fat": "fat_g", "mass_g": "mass_g"}


def number(value):
    return type(value) in (int, float) and math.isfinite(value)


def percentile(values, q):
    if not values:
        return None
    values = sorted(values)
    pos = (len(values) - 1) * q
    low = int(pos)
    return values[low] + (values[min(low + 1, len(values) - 1)] - values[low]) * (pos - low)


def nutrient_metrics(pairs, selected_count):
    """pairs=(truth,prediction). Missing predictions never become zero estimates."""
    valid = [(truth, pred) for truth, pred in pairs if number(truth) and number(pred)]
    errors = [pred - truth for truth, pred in valid]
    absolute = [abs(error) for error in errors]
    apes = [abs(pred - truth) / abs(truth) * 100 for truth, pred in valid if truth != 0]
    within = sum(abs(pred - truth) <= .15 * abs(truth) for truth, pred in valid)
    total_truth = sum(abs(truth) for truth, _ in valid)
    return {
        "selected_count": selected_count,
        "valid_prediction_count": len(valid),
        "missing_prediction_count": selected_count - len(valid),
        "coverage_percent": len(valid) / selected_count * 100 if selected_count else None,
        "mae": statistics.fmean(absolute) if absolute else None,
        "mean_error_bias": statistics.fmean(errors) if errors else None,
        "mape_percent": statistics.fmean(apes) if apes else None,
        "median_ape_percent": statistics.median(apes) if apes else None,
        "p90_ape_percent": percentile(apes, .9),
        "mape_nonzero_truth_count": len(apes),
        "mape_zero_truth_excluded_count": len(valid) - len(apes),
        "wape_percent_mae_over_mean_truth": sum(absolute) / total_truth * 100 if total_truth else None,
        "within_15_percent_count": within,
        "within_15_percent_of_all_selected": within / selected_count * 100 if selected_count else None,
        "within_15_percent_of_valid_predictions": within / len(valid) * 100 if valid else None,
    }


def bootstrap_mean_ci(values, repetitions=2000):
    if not values:
        return None
    if max(values) == min(values):
        return [values[0], values[0]]
    rng = random.Random(20261025)
    boot = [statistics.fmean(rng.choices(values, k=len(values))) for _ in range(repetitions)]
    return [percentile(boot, .025), percentile(boot, .975)]


def prediction(row, nutrient):
    if row.get("status") != "success":
        return None
    return (row.get("totals") or {}).get(nutrient)


def summarize(manifest, versions):
    result = {}
    for name, predictions in versions.items():
        status = Counter(predictions.get(sample_id(row), {}).get("status", "missing") for row in manifest)
        selected_candidates = [candidate for row in manifest for candidate in predictions.get(sample_id(row), {}).get("selected", [])]
        result[name] = {"status_counts": dict(status),
                       "selected_food_groups": len(selected_candidates),
                       "selected_packaged_foods": sum(bool(c.get("package_present")) for c in selected_candidates),
                       "selected_foods_with_printed_kcal": sum(c.get("printed_kcal") is not None for c in selected_candidates),
                       "selected_foods_with_grounded_label": sum(bool(c.get("grounded_label_present")) for c in selected_candidates),
                       "nutrition_source_counts": dict(Counter(c.get("source") for c in selected_candidates)),
                       "nutrients": {
            nutrient: nutrient_metrics([(row["truth"][truth_key], prediction(predictions.get(sample_id(row), {}), nutrient)) for row in manifest], len(manifest))
            for nutrient, truth_key in MAPPING.items()
        }}
    return result


def minimum_confidence_bin(row):
    selected = row.get("selected") or []
    confidence = [candidate.get("confidence") for candidate in selected]
    if not confidence or any(not number(value) or not 0 <= value <= 1 for value in confidence):
        return "missing_confidence"
    value = min(confidence)
    if value < .5:
        return "[0,0.5)"
    if value < .75:
        return "[0.5,0.75)"
    if value < .9:
        return "[0.75,0.9)"
    return "[0.9,1]"


def confidence_exploration(manifest, predictions):
    bins = {}
    for label in ("[0,0.5)", "[0.5,0.75)", "[0.75,0.9)", "[0.9,1]", "missing_confidence"):
        subset = [row for row in manifest if minimum_confidence_bin(predictions.get(sample_id(row), {})) == label]
        metric = nutrient_metrics([(row["truth"]["calories_kcal"], prediction(predictions.get(sample_id(row), {}), "calories")) for row in subset], len(subset))
        metric["percent_of_entire_selected_set"] = len(subset) / len(manifest) * 100 if manifest else None
        metric["within_15_percent_contribution_to_entire_selected_set"] = metric["within_15_percent_count"] / len(manifest) * 100 if manifest else None
        bins[label] = metric
    return {
        "exploratory": True, "definition": "Minimum food-name confidence among the selected top candidate of each dish food group",
        "not_a_calorie_accuracy_probability": True, "thresholds_tuned_on_results": False,
        "missing_nutrition_stays_in_bin_denominator": True, "bins": bins,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=["pilot", "blind_test"], required=True)
    parser.add_argument("--manifest", type=Path, default=ROOT / "data/nutrition5k/selection_manifest.jsonl")
    parser.add_argument("--freeze", type=Path, default=EVAL / "manifest_freeze.json")
    parser.add_argument("--with-db", action="store_true")
    args = parser.parse_args()
    frozen = read_json(args.freeze)
    if sha256(args.manifest.read_bytes()) != frozen["manifest_sha256"]:
        raise RuntimeError("Manifest mismatch")
    manifest = [r for r in read_jsonl(args.manifest) if r["split"] == args.split]
    suffix = "with_db" if args.with_db else "no_db"
    versions = {name: {r["sample_id"]: r for r in read_jsonl(EVAL / "results" / f"{args.split}_{name}_{suffix}.jsonl")}
                for name in ("baseline", "improved")}
    versions["raw_model"] = {key: row.get("raw_model_prediction") or {"status": "not_attempted"}
                              for key, row in versions["baseline"].items()}
    raw = {}
    for row in manifest:
        path = EVAL / "raw_responses" / f"{sample_id(row)}.json"
        if path.exists():
            raw[sample_id(row)] = read_json(path)
    pairs = []
    changes = []
    case_metrics = []
    transitions = Counter()
    for row in manifest:
        identifier = sample_id(row)
        before, after = (versions[name].get(identifier, {}) for name in ("baseline", "improved"))
        old, new = prediction(before, "calories"), prediction(after, "calories")
        both_valid = number(old) and number(new)
        truth = row["truth"]["calories_kcal"]
        if both_valid:
            difference = abs(new - truth) - abs(old - truth)
            pairs.append(difference)
            category = "improved" if difference < -1e-9 else "worsened" if difference > 1e-9 else "same_error"
        elif number(old):
            category = "valid_to_missing"
        elif number(new):
            category = "missing_to_valid"
        else:
            category = "both_missing"
        transitions[category] += 1
        case = {"sample_id": identifier, "original_split": row["original_split"],
                "camera_view": row["camera_view"], "group_id": row["group_id"],
                "image_path": row["image_path"], "source_url": row["source_url"],
                "baseline_status": before.get("status"), "improved_status": after.get("status"),
                "transition": category}
        for nutrient, truth_key in MAPPING.items():
            case[f"truth_{nutrient}"] = row["truth"][truth_key]
            for version in ("baseline", "improved", "raw_model"):
                value = prediction(versions[version].get(identifier, {}), nutrient)
                case[f"{version}_{nutrient}"] = value
                case[f"{version}_{nutrient}_absolute_error"] = abs(value - row["truth"][truth_key]) if number(value) else None
        case_metrics.append(case)
        changed = before.get("status") != after.get("status") or before.get("totals") != after.get("totals") or before.get("selected") != after.get("selected")
        if changed or category == "valid_to_missing":
            changes.append({"sample_id": identifier, "transition": category,
                            "truth_calories_kcal": truth, "baseline_calories_kcal": old, "improved_calories_kcal": new,
                            "baseline_status": before.get("status"), "improved_status": after.get("status"),
                            "baseline_selected": before.get("selected"), "improved_selected": after.get("selected"),
                            "manual_false_rejection_review": "required" if category == "valid_to_missing" else "not_applicable"})
    latency = [r["latency_ms"] for r in raw.values() if number(r.get("latency_ms"))]
    attempted_count = sum("latency_ms" in r for r in raw.values())
    received_count = sum(r["status"] == "response_received" for r in raw.values())
    unavailable = [sample_id(row) for row in manifest if not image_path(row).is_file()]
    unattempted_reasons = Counter(
        raw.get(sample_id(row), {}).get("status", "source_image_unavailable" if sample_id(row) in unavailable else "not_attempted")
        for row in manifest if "latency_ms" not in raw.get(sample_id(row), {}))
    summary = {
        "generated_at": utc_now(), "split": args.split, "manifest_sha256": frozen["manifest_sha256"],
        "selected_dishes": len(manifest), "locally_present_images": sum(image_path(r).is_file() for r in manifest),
        "attempted_generations": attempted_count,
        "responses_received": received_count,
        "source_images_unavailable_count": len(unavailable),
        "source_images_unavailable_sample_ids": unavailable,
        "unattempted_reason_counts": dict(unattempted_reasons),
        "api_generation_failed_count": sum(r["status"] == "generation_failed" for r in raw.values()),
        "api_response_rate_of_attempted_percent": received_count / attempted_count * 100 if attempted_count else None,
        "response_coverage_of_all_selected_percent": received_count / len(manifest) * 100 if manifest else None,
        "valid_json_objects": sum(r.get("json_object_valid") is True for r in raw.values()),
        "collection_status_counts": dict(Counter(raw.get(sample_id(r), {}).get("status", "not_attempted") for r in manifest)),
        "model_versions": dict(Counter(r.get("model_version", "unknown") for r in raw.values())),
        "latency_ms": {"count": len(latency), "p50": percentile(latency, .5), "p95": percentile(latency, .95)},
        "versions": summarize(manifest, versions),
        "paired_calories": {"valid_pair_count": len(pairs), "transition_counts": dict(transitions),
                            "changed_prediction_cases": len(changes),
                            "mean_absolute_error_delta_improved_minus_baseline": statistics.fmean(pairs) if pairs else None,
                            "bootstrap_95_percent_ci": bootstrap_mean_ci(pairs), "bootstrap_repetitions": 2000,
                            "positive_delta_means_worse": True},
        "exploratory_confidence_vs_calorie_error": confidence_exploration(manifest, versions["improved"]),
        "strata": {field: {value: summarize([r for r in manifest if str(r.get(field)) == value], versions)
                            for value in sorted({str(r.get(field)) for r in manifest})}
                   for field in ("original_split", "camera_view")},
        "cost_all_splits": read_json(EVAL / "cost_summary.json"),
        "scope": {"nutrition_db": args.with_db, "grounding": False, "habit_correction": False,
                  "menu_classification_accuracy_measured": False, "production_model_verified": False,
                  "physical_dish_independence_verified": False},
    }
    atomic_json(EVAL / "results" / f"{args.split}_{suffix}_summary.json", summary)
    write_jsonl(EVAL / "results" / f"{args.split}_{suffix}_changed_cases.jsonl", changes)
    case_path = EVAL / "results" / f"{args.split}_{suffix}_case_metrics.csv"
    if case_metrics:
        with case_path.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(case_metrics[0]))
            writer.writeheader()
            writer.writerows(case_metrics)
    print({"split": args.split, "selected": len(manifest), "responses": summary["responses_received"],
           "changed_cases": len(changes), "improved_calories": summary["versions"]["improved"]["nutrients"]["calories"]})


if __name__ == "__main__":
    main()
