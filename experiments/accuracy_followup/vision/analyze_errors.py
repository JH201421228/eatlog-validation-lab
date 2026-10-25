"""Exploratory error decomposition of the already-opened 1,000-case evaluation.

This file reads truth only to diagnose old results. It is not imported by any
prompt/request builder and cannot produce corrected production predictions.
"""
from __future__ import annotations

import json
import math
import statistics
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]


def describe(rows):
    if not rows:
        return {"n": 0}
    def mean(key):
        return statistics.fmean(row[key] for row in rows)
    return {"n": len(rows), "calorie_mae": mean("calorie_absolute_error"),
            "calorie_mape_percent": mean("calorie_ape"), "mass_mae_g": mean("mass_absolute_error"),
            "mass_mape_percent": mean("mass_ape"),
            "median_mass_ratio": statistics.median(row["mass_ratio"] for row in rows),
            "median_density_ratio": statistics.median(row["density_ratio"] for row in rows),
            "within_15_percent_count": sum(row["calorie_ape"] <= 15 for row in rows),
            "within_15_percent_rate": sum(row["calorie_ape"] <= 15 for row in rows) / len(rows) * 100}


def main():
    truth = {row["sample_id"]: row for row in jsonl(ROOT / "data/nutrition5k/selection_manifest_v3.jsonl") if row["split"] == "blind_test"}
    predictions = jsonl(ROOT / "evaluation/results/blind_test_improved_no_db.jsonl")
    cases, mass_groups, count_groups, view_groups = [], defaultdict(list), defaultdict(list), defaultdict(list)
    serving_values, food_names, signs = Counter(), Counter(), Counter()
    for prediction in predictions:
        if prediction["status"] != "success":
            continue
        row = truth[prediction["sample_id"]]
        actual, predicted = row["truth"], prediction["totals"]
        tm, pm = actual["mass_g"], predicted["mass_g"]
        tc, pc = actual["calories_kcal"], predicted["calories"]
        if min(tm, pm, tc) <= 0 or pc < 0:
            continue
        td, pd = tc / tm, pc / pm
        mass_component = (pm - tm) * (pd + td) / 2
        density_component = (pd - td) * (pm + tm) / 2
        assert math.isclose(mass_component + density_component, pc - tc, abs_tol=1e-8)
        case = {"sample_id": row["sample_id"], "calorie_absolute_error": abs(pc-tc), "calorie_ape": abs(pc-tc)/tc*100,
                "mass_absolute_error": abs(pm-tm), "mass_ape": abs(pm-tm)/tm*100,
                "mass_ratio": pm/tm, "density_ratio": pd/td,
                "symmetric_mass_error_component_kcal": mass_component,
                "symmetric_density_error_component_kcal": density_component,
                "dominant_component": "mass" if abs(mass_component)>abs(density_component) else "density",
                "oracle_mass_error_kcal": abs(pc*tm/pm-tc),
                "oracle_density_error_kcal": abs(pm*td-tc),
                "food_group_count": prediction["food_groups"]}
        cases.append(case)
        mass_bin = "<100g" if tm < 100 else "100-199g" if tm < 200 else "200-399g" if tm < 400 else "400-799g" if tm < 800 else ">=800g"
        mass_groups[mass_bin].append(case)
        count_groups[str(prediction["food_groups"])].append(case)
        view_groups[row["camera_view"]].append(case)
        signs[("mass_high" if pm>tm else "mass_low")+"/"+("density_high" if pd>td else "density_low")] += 1
        for candidate in prediction["selected"]:
            serving_values[candidate["grams"]] += 1
            food_names[candidate["food_name"]] += 1
    output = {
        "purpose": "Exploratory causes only. The old 1,000-case set is no longer a confirmatory holdout.",
        "not_deployable_ground_truth_oracle": True,
        "valid_cases": describe(cases),
        "symmetric_decomposition": {
            "identity": "predC-trueC=(predM-trueM)*(predDensity+trueDensity)/2+(predDensity-trueDensity)*(predM+trueM)/2",
            "mass_dominant_cases": sum(row["dominant_component"] == "mass" for row in cases),
            "density_dominant_cases": sum(row["dominant_component"] == "density" for row in cases),
            "mean_abs_mass_component": statistics.fmean(abs(row["symmetric_mass_error_component_kcal"]) for row in cases),
            "mean_abs_density_component": statistics.fmean(abs(row["symmetric_density_error_component_kcal"]) for row in cases),
            "warning": "Absolute components do not add to MAE because their signs can cancel.",
        },
        "oracle_mass_only_mae_kcal": statistics.fmean(row["oracle_mass_error_kcal"] for row in cases),
        "oracle_density_only_mae_kcal": statistics.fmean(row["oracle_density_error_kcal"] for row in cases),
        "error_sign_quadrants": dict(signs),
        "by_truth_mass_for_diagnosis_only": {key: describe(value) for key,value in mass_groups.items()},
        "by_predicted_food_count": {key: describe(value) for key,value in count_groups.items()},
        "by_camera_view": {key: describe(value) for key,value in view_groups.items()},
        "food_group_grams_mode_counts": serving_values.most_common(20),
        "selected_food_group_count": sum(serving_values.values()),
        "food_groups_at_multiple_of_50g": sum(n for g,n in serving_values.items() if g and g % 50 == 0),
        "predicted_food_name_counts_not_truth_classification": food_names.most_common(30),
    }
    (HERE / "error_analysis.json").write_text(json.dumps(output, ensure_ascii=False, indent=2),encoding="utf-8")
    (HERE / "error_decomposition_cases.jsonl").write_text("".join(json.dumps(row,ensure_ascii=False)+"\n" for row in cases),encoding="utf-8")
    print(json.dumps({key: output[key] for key in ("valid_cases","symmetric_decomposition","oracle_mass_only_mae_kcal","oracle_density_only_mae_kcal","error_sign_quadrants","food_groups_at_multiple_of_50g","selected_food_group_count","by_truth_mass_for_diagnosis_only")},ensure_ascii=False,indent=2))


if __name__ == "__main__":
    main()
