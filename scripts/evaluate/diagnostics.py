"""Post hoc diagnostics; never change frozen labels, requests, or primary scores."""
from __future__ import annotations

from common import ROOT, EVAL, atomic_json, image_path, read_jsonl, sample_id, sha256, utc_now
from metrics import nutrient_metrics, number


def main():
    manifest_path = ROOT / "data/nutrition5k/selection_manifest_v3.jsonl"
    manifest = [row for row in read_jsonl(manifest_path) if row["split"] == "blind_test"]
    predictions = {row["sample_id"]: row for row in read_jsonl(EVAL / "results/blind_test_improved_no_db.jsonl")}
    pairs, original_pairs, density_pairs = [], [], []
    details = []
    for row in manifest:
        pred = predictions.get(sample_id(row), {})
        totals = pred.get("totals") or {}
        kcal, mass = totals.get("calories"), totals.get("mass_g")
        truth_kcal, truth_mass = row["truth"]["calories_kcal"], row["truth"]["mass_g"]
        valid = pred.get("status") == "success" and all(number(v) for v in (kcal, mass, truth_kcal, truth_mass)) and mass > 0 and truth_mass > 0
        corrected = kcal * truth_mass / mass if valid else None
        pairs.append((truth_kcal, corrected))
        original_pairs.append((truth_kcal, kcal if valid else None))
        if valid:
            density_pairs.append((100 * truth_kcal / truth_mass, 100 * kcal / mass))
        details.append({"sample_id": sample_id(row), "eligible": valid,
                        "original_predicted_calories": kcal, "predicted_mass_g": mass,
                        "truth_mass_g_used_as_oracle_input": truth_mass,
                        "oracle_mass_adjusted_calories": corrected})
    atomic_json(EVAL / "results/oracle_mass_diagnostic.json", {
        "generated_at": utc_now(), "manifest_sha256": sha256(manifest_path.read_bytes()),
        "post_hoc_exploratory": True, "new_model_calls": 0,
        "formula": "predicted_calories * ground_truth_total_mass / predicted_total_mass",
        "interpretation": "Replace only total-mass error with measured truth; keep predicted whole-dish energy density/composition.",
        "not_a_model_accuracy_improvement_or_deployed_feature": True,
        "uses_ground_truth_input_unavailable_to_the_photo_only_model": True,
        "does_not_supply_correct_ingredient_weights_or_nutrition_density": True,
        "zero_mass_error_would_be_by_construction_not_an_achievement": True,
        "original_calorie_metrics_same_eligible_cases": nutrient_metrics(original_pairs, len(manifest)),
        "oracle_mass_calorie_metrics": nutrient_metrics(pairs, len(manifest)),
        "whole_dish_density_kcal_per_100g_metrics": nutrient_metrics(density_pairs, len(manifest)),
        "case_diagnostics": details,
    })
    reviews = {
        "dish_1559172356": "Official overhead RGB visibly shows a mounted smartphone and capture apparatus; no food is visible.",
        "dish_1561997365": "Camera B frame 0 shows the outside/bottom of a bowl and capture apparatus; the food contents are not discernible.",
    }
    reviewed = []
    lookup = {sample_id(row): row for row in manifest}
    for identifier, finding in reviews.items():
        row = lookup[identifier]
        reviewed.append({"sample_id": identifier, "image_path": row["image_path"],
                         "image_sha256": sha256(image_path(row).read_bytes()),
                         "source_url": row["source_url"], "camera_view": row["camera_view"],
                         "raw_model_candidates_empty": True, "baseline_and_improved_reason": "not_food",
                         "visual_observation": finding,
                         "interpretation": "Abstention is consistent with image visibility. Do not label this a new-filter false rejection or a confirmed food-recognition error.",
                         "primary_denominator_unchanged": True})
    atomic_json(EVAL / "results/abstention_visual_review.json", {
        "reviewed_at": utc_now(), "method": "Assistant inspected the two original local images with view_image after final collection.",
        "scope": "Two empty-candidates cases only; not a semantic audit of all 999 images.",
        "no_image_replacement_or_label_change_or_retry": True,
        "dataset_limit": "Positive nutrition metadata and checksum-valid image files do not guarantee visible food or correct image-label semantic alignment.",
        "cases": reviewed,
    })
    print({"oracle_eligible": sum(row["eligible"] for row in details),
           "oracle_calories": nutrient_metrics(pairs, len(manifest)), "visually_reviewed_abstentions": len(reviewed)})


if __name__ == "__main__":
    main()
