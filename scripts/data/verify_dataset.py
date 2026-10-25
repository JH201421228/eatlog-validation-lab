"""Independent source/label/hash audit of the fixed Nutrition5k sample set.

Does not call the metadata parser to check column mapping. Does not read any
model response, score, or evaluation output. All checks use public source files.
"""
from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

from collect_nutrition5k import DATA, ROOT, SOURCE, dump_json, read_jsonl, utc_now


def file_hashes(path):
    sha256 = hashlib.sha256()
    md5 = hashlib.md5()
    size = 0
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            sha256.update(block)
            md5.update(block)
            size += len(block)
    return {"sha256": sha256.hexdigest(), "md5": md5.hexdigest(), "size_bytes": size}


def main():
    frozen_path = DATA / "selection_manifest_v3.jsonl"
    frozen = read_jsonl(frozen_path)
    rows = read_jsonl(DATA / "manifest.jsonl")
    by_id = {row["sample_id"]: row for row in rows}
    source_provenance = json.loads((SOURCE / "provenance.json").read_text())
    failures = []
    checked_sources = []
    for source in source_provenance["files"]:
        actual = file_hashes(ROOT / source["path"])
        valid = all(actual[key] == source[key] for key in ("sha256", "md5", "size_bytes"))
        if source.get("official_md5") and actual["md5"] != source["official_md5"]:
            valid = False
        checked_sources.append({"path": source["path"], "hash_valid": valid, **actual})
        if not valid:
            failures.append({"path": source["path"], "reason": "official_metadata_file_modified"})
    raw_tables = {}
    raw_row_count = 0
    wrong_structure = []
    for cafe in ("cafe1", "cafe2"):
        path = SOURCE / "metadata" / f"dish_metadata_{cafe}.csv"
        with path.open(encoding="utf-8", newline="") as file:
            table = list(csv.reader(file))
        raw_tables[path.relative_to(ROOT).as_posix()] = table
        raw_row_count += len(table)
        for index, fields in enumerate(table, 1):
            if len(fields) < 13 or (len(fields) - 6) % 7:
                wrong_structure.append({"file": path.name, "line": index, "columns": len(fields)})
    label_failures = []
    ingredient_count = 0
    for row in frozen:
        fields = raw_tables[row["metadata_path"]][row["metadata_line"] - 1]
        if fields[0] != row["dish_id"]:
            label_failures.append({"dish_id": row["dish_id"], "reason": "wrong_source_row"})
        independent_truth = {"calories_kcal": float(fields[1]), "mass_g": float(fields[2]),
            "fat_g": float(fields[3]), "carbs_g": float(fields[4]), "protein_g": float(fields[5])}
        if row["truth"] != independent_truth:
            label_failures.append({"dish_id": row["dish_id"], "reason": "dish_truth_differs_from_raw_columns"})
        expected_ingredient_count = (len(fields) - 6) // 7
        if len(row["ingredients"]) != expected_ingredient_count:
            label_failures.append({"dish_id": row["dish_id"], "reason": "ingredient_count_differs"})
        for item_index, ingredient in enumerate(row["ingredients"]):
            base = 6 + 7 * item_index
            expected = {"ingredient_id": fields[base], "name": fields[base + 1], "mass_g": float(fields[base + 2]),
                "calories_kcal": float(fields[base + 3]), "fat_g": float(fields[base + 4]),
                "carbs_g": float(fields[base + 5]), "protein_g": float(fields[base + 6])}
            ingredient_count += 1
            if ingredient != expected:
                label_failures.append({"dish_id": row["dish_id"], "ingredient_index": item_index, "reason": "ingredient_mapping_differs"})
    mapping = {"verified_at_utc": utc_now(), "raw_rows_examined_for_structure": raw_row_count,
        "base_columns": 6, "repeating_ingredient_columns": 7, "wrong_structure": wrong_structure,
        "frozen_rows_checked_against_raw_values": len(frozen), "ingredient_rows_checked": ingredient_count,
        "field_mapping": {"dish_id": 0, "calories_kcal": 1, "mass_g": 2, "fat_g": 3, "carbs_g": 4, "protein_g": 5},
        "truth_values_unchanged": not label_failures, "mapping_failures": label_failures,
        "cafe2_zero_nutrient_rows_excluded": all(row["cafe"] == "cafe1" for row in frozen)}
    dump_json(DATA / "label_mapping_validation.json", mapping)
    failures.extend(label_failures)
    failures.extend(wrong_structure)
    source_md5_checks = 0
    image_hash_checks = 0
    original_video_checks = 0
    image_hashes = []
    source_bytes = 0
    image_bytes = 0
    missing = []
    for expected in frozen:
        row = by_id[expected["sample_id"]]
        if row["download_status"] != "ok":
            missing.append({"sample_id": row["sample_id"], "split": row["split"], "source_key": row["source_key"], "reason": row.get("download_error", "not_downloaded")})
            continue
        actual = file_hashes(ROOT / row["image_path"])
        image_hash_checks += 1
        image_bytes += actual["size_bytes"]
        image_hashes.append(actual["sha256"])
        if actual["sha256"] != row["image_sha256"] or actual["md5"] != row["image_md5"]:
            failures.append({"sample_id": row["sample_id"], "reason": "actual_image_hash_mismatch"})
        if row["camera_view"] == "overhead_rgb":
            source_actual = actual
        else:
            source_actual = file_hashes(ROOT / row["source_download"]["local_video_path"])
            original_video_checks += 1
            if row["extraction"]["frame_index"] != 0 or row["frame_index"] != 0:
                failures.append({"sample_id": row["sample_id"], "reason": "frame_index_changed"})
        source_bytes += source_actual["size_bytes"]
        source_md5_checks += 1
        if source_actual["md5"] != row["source_object"]["md5"] or source_actual["size_bytes"] != row["source_object"]["size_bytes"]:
            failures.append({"sample_id": row["sample_id"], "reason": "actual_source_differs_from_official_md5_size"})
        if source_actual["sha256"] != row["source_download"]["sha256"]:
            failures.append({"sample_id": row["sample_id"], "reason": "source_sha256_changed_since_download"})
        if row["source_object"]["key"] != row["source_key"] or not row["source_url"].endswith("/" + row["source_key"]):
            failures.append({"sample_id": row["sample_id"], "reason": "source_key_url_object_disagree"})
    pilot = [row for row in frozen if row["split"] == "pilot"]
    evaluation = [row for row in frozen if row["split"] == "blind_test"]
    pilot_ids = {row["sample_id"] for row in pilot}
    eval_ids = {row["sample_id"] for row in evaluation}
    pilot_groups = {row["group_id"] for row in pilot}
    eval_groups = {row["group_id"] for row in evaluation}
    old_pilot = [row for row in read_jsonl(DATA / "archive/v1_before_quality_audit/selection_manifest.jsonl") if row["split"] == "pilot"]
    old_pilot_groups = {row["group_id"] for row in old_pilot}
    if pilot_ids & eval_ids or pilot_groups & eval_groups or old_pilot_groups & eval_groups:
        failures.append({"reason": "pilot_evaluation_overlap"})
    original_train = set((SOURCE / "dish_ids/splits/rgb_train_ids.txt").read_text().splitlines())
    original_test = set((SOURCE / "dish_ids/splits/rgb_test_ids.txt").read_text().splitlines())
    for row in frozen:
        expected_set = original_train if row["original_split"] == "train" else original_test
        if row["sample_id"] not in expected_set:
            failures.append({"sample_id": row["sample_id"], "reason": "official_split_mapping_error"})
    if len(image_hashes) != len(set(image_hashes)):
        failures.append({"reason": "duplicate_image_sha256"})
    summary = {"verified_at_utc": utc_now(), "selection_manifest": frozen_path.relative_to(ROOT).as_posix(),
        "selection_sha256": file_hashes(frozen_path)["sha256"],
        "selected": len(frozen), "selected_pilot": len(pilot), "selected_evaluation": len(evaluation),
        "available_images": image_hash_checks, "available_pilot_images": sum(by_id[row["sample_id"]]["download_status"] == "ok" for row in pilot),
        "available_evaluation_images": sum(by_id[row["sample_id"]]["download_status"] == "ok" for row in evaluation),
        "missing_source_rows": missing, "actual_source_md5_against_official_checks": source_md5_checks,
        "actual_image_sha256_checks": image_hash_checks, "original_side_video_hash_checks": original_video_checks,
        "unique_image_sha256": len(set(image_hashes)), "duplicate_image_sha256_count": len(image_hashes) - len(set(image_hashes)),
        "unique_dish_ids": len({row["dish_id"] for row in frozen}), "unique_inferred_groups": len({row["group_id"] for row in frozen}),
        "pilot_evaluation_dish_overlap": sorted(pilot_ids & eval_ids), "pilot_evaluation_group_overlap": sorted(pilot_groups & eval_groups),
        "original_v1_pilot_group_in_evaluation": sorted(old_pilot_groups & eval_groups),
        "available_by_view": dict(Counter(row["camera_view"] for row in rows if row["download_status"] == "ok")),
        "actual_selected_image_bytes": image_bytes, "actual_selected_source_bytes": source_bytes,
        "source_metadata_hash_checks": checked_sources, "independent_label_mapping_pass": not label_failures and not wrong_structure,
        "integrity_failures": failures, "all_available_artifacts_verified": not failures,
        "completeness_note": "The frozen denominator retains unavailable source rows. Integrity success does not imply all selected sources exist."}
    dump_json(DATA / "final_integrity_audit.json", summary)
    print(json.dumps({key: value for key, value in summary.items() if key != "source_metadata_hash_checks"}, indent=2))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
