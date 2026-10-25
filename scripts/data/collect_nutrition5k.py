"""Reproducible, bounded download of public Nutrition5k overhead RGB data.

Only individual metadata/image objects are fetched; never the full archive.
Python standard library only. Run from any working directory.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import csv
import hashlib
import json
import math
import random
import re
import shutil
import struct
import subprocess
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zlib
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "nutrition5k"
SOURCE = DATA / "source"
BUCKET = "https://storage.googleapis.com/nutrition5k_dataset"
PREFIX = "nutrition5k_dataset/"
DATASET_REPO = "https://github.com/google-research-datasets/Nutrition5k"
LICENSE = "CC-BY-4.0"
LICENSE_URL = "https://creativecommons.org/licenses/by/4.0/"
SEED = "eatlog-public-nutrition5k-2026-10-25-v1"
GROUP_WINDOW_SECONDS = 600
GROUP_MASS_TOLERANCE_G = 0.002
NS = {"s3": "http://doc.s3.amazonaws.com/2006-03-01"}
SOURCE_FILES = [
    "metadata/dish_metadata_cafe1.csv",
    "metadata/dish_metadata_cafe2.csv",
    "metadata/ingredients_metadata.csv",
    "dish_ids/README",
    "dish_ids/dish_ids_all.txt",
    "dish_ids/dish_ids_cafe1.txt",
    "dish_ids/dish_ids_cafe2.txt",
    "dish_ids/splits/depth_test_ids.txt",
    "dish_ids/splits/depth_train_ids.txt",
    "dish_ids/splits/rgb_test_ids.txt",
    "dish_ids/splits/rgb_train_ids.txt",
]


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def fetch(url: str, attempts: int = 5) -> bytes:
    for attempt in range(attempts):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "eatlog-validation-lab/1.0 (public dataset research)"})
            with urllib.request.urlopen(request, timeout=60) as response:
                return response.read()
        except Exception:
            if attempt + 1 == attempts:
                raise
            time.sleep(min(2 ** attempt, 8))
    raise AssertionError("unreachable")


def dump_json(path: Path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def dump_jsonl(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows), encoding="utf-8")
    temporary.replace(path)


def read_jsonl(path: Path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def hash_bytes(blob: bytes):
    return {"sha256": hashlib.sha256(blob).hexdigest(), "md5": hashlib.md5(blob).hexdigest(), "size_bytes": len(blob)}


def publish_bytes(path: Path, blob: bytes):
    """Publish only complete, already verified bytes to a collector-visible path."""
    temporary = path.with_name(path.stem + ".partial" + path.suffix)
    temporary.write_bytes(blob)
    temporary.replace(path)


def list_objects(prefix):
    results = []
    marker = None
    while True:
        params = {"prefix": prefix, "max-keys": "1000"}
        if marker:
            params["marker"] = marker
        doc = ET.fromstring(fetch(BUCKET + "?" + urllib.parse.urlencode(params)))
        for item in doc.findall("s3:Contents", NS):
            values = {child.tag.rsplit("}", 1)[-1]: child.text for child in item}
            results.append({"key": values["Key"], "generation": values["Generation"],
                            "md5": values["ETag"].strip('"'), "size_bytes": int(values["Size"]),
                            "last_modified": values["LastModified"]})
        if doc.findtext("s3:IsTruncated", namespaces=NS) != "true":
            break
        marker = doc.findtext("s3:NextMarker", namespaces=NS)
        if not marker:
            raise ValueError("Truncated object list missing continuation marker")
        print(f"listed {len(results)} objects", flush=True)
    return results


def fetch_sources():
    SOURCE.mkdir(parents=True, exist_ok=True)
    provenance = []
    def get_one(relative):
        url = BUCKET + "/" + PREFIX + relative
        blob = fetch(url)
        target = SOURCE / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(blob)
        return {"path": target.relative_to(ROOT).as_posix(), "url": url, "retrieved_at_utc": utc_now(), **hash_bytes(blob)}
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        for result in pool.map(get_one, SOURCE_FILES):
            provenance.append(result)
            print("saved " + result["path"], flush=True)
    commit = json.loads(fetch("https://api.github.com/repos/google-research-datasets/Nutrition5k/commits/main"))["sha"]
    url = f"https://raw.githubusercontent.com/google-research-datasets/Nutrition5k/{commit}/README.md"
    blob = fetch(url)
    (SOURCE / "README.upstream.md").write_bytes(blob)
    provenance.append({"path": (SOURCE / "README.upstream.md").relative_to(ROOT).as_posix(), "url": url,
                       "upstream_commit": commit, "retrieved_at_utc": utc_now(), **hash_bytes(blob)})
    rgb_objects = [item for item in list_objects(PREFIX + "imagery/realsense_overhead/") if item["key"].endswith("/rgb.png")]
    dump_json(SOURCE / "overhead_rgb_objects.json", {"listed_at_utc": utc_now(), "bucket": BUCKET,
              "prefix": PREFIX + "imagery/realsense_overhead/", "objects": rgb_objects})
    metadata_objects = list_objects(PREFIX + "metadata/") + list_objects(PREFIX + "dish_ids/")
    dump_json(SOURCE / "metadata_objects.json", metadata_objects)
    object_by_key = {item["key"]: item for item in metadata_objects}
    for row in provenance:
        key = row["url"].removeprefix(BUCKET + "/")
        if key in object_by_key:
            row["gcs_generation"] = object_by_key[key]["generation"]
            row["official_md5"] = object_by_key[key]["md5"]
            if row["md5"] != row["official_md5"]:
                raise ValueError("Metadata MD5 mismatch: " + key)
    dump_json(SOURCE / "provenance.json", {"retrieved_at_utc": utc_now(), "dataset_repo": DATASET_REPO,
              "upstream_commit": commit, "license": LICENSE, "license_url": LICENSE_URL, "files": provenance})
    print(json.dumps({"overhead_rgb_objects": len(rgb_objects), "upstream_commit": commit}), flush=True)


def parse_metadata():
    rows = {}
    exclusions = []
    for cafe in ("cafe1", "cafe2"):
        path = SOURCE / "metadata" / f"dish_metadata_{cafe}.csv"
        with path.open(newline="", encoding="utf-8") as file:
            for line_number, fields in enumerate(csv.reader(file), 1):
                dish_id = fields[0] if fields else ""
                try:
                    if not re.fullmatch(r"dish_\d{10}", dish_id):
                        raise ValueError("invalid_dish_id")
                    # The released CSV is six base columns + repeating SEVEN columns,
                    # without num_ingrs. This differs from the upstream README prose.
                    if len(fields) < 13 or (len(fields) - 6) % 7:
                        raise ValueError("invalid_field_count")
                    values = [float(x) for x in fields[1:6]]
                    if any(not math.isfinite(x) or x < 0 for x in values) or values[1] <= 0:
                        raise ValueError("invalid_dish_numeric_labels")
                    calories, mass, fat, carbs, protein = values
                    ingredients = []
                    for start in range(6, len(fields), 7):
                        ingr_id, name = fields[start:start + 2]
                        nums = [float(x) for x in fields[start + 2:start + 7]]
                        if not re.fullmatch(r"ingr_\d{10}", ingr_id) or any(not math.isfinite(x) or x < 0 for x in nums):
                            raise ValueError("invalid_ingredient_numeric_labels")
                        ingredients.append(dict(zip(("ingredient_id", "name", "mass_g", "calories_kcal", "fat_g", "carbs_g", "protein_g"), [ingr_id, name, *nums])))
                    if dish_id in rows:
                        raise ValueError("duplicate_dish_id")
                    rows[dish_id] = {"dish_id": dish_id, "cafe": cafe, "timestamp": int(dish_id[5:]),
                        "truth": {"calories_kcal": calories, "mass_g": mass, "fat_g": fat, "carbs_g": carbs, "protein_g": protein},
                        "ingredients": ingredients, "metadata_path": path.relative_to(ROOT).as_posix(), "metadata_line": line_number}
                except ValueError as error:
                    exclusions.append({"dish_id": dish_id, "reason": str(error), "path": path.relative_to(ROOT).as_posix(), "line": line_number})
    return rows, exclusions


def stable_order(kind, identifier):
    return hashlib.sha256(f"{SEED}|{kind}|{identifier}".encode()).hexdigest()


def inferred_groups(rows):
    """Conservative heuristic, NOT an official plate identity annotation.

    Join scans from the same cafe within ten minutes if the smaller ingredient
    set is contained in the larger, every old ingredient mass is retained or
    increased, and at least one >=1g ingredient retains the same mass (+/-2mg).
    Shared oils/spices can increase when another recipe is added to a plate.
    Exact mass equality for *all* ingredients would miss those incremental scans.
    Transitive union may over-merge unrelated nearby plates; incomplete metadata
    can also leave genuine repeated plates separate. Independence is not proven.
    """
    parent = {dish_id: dish_id for dish_id in rows}
    def find(dish_id):
        while parent[dish_id] != dish_id:
            parent[dish_id] = parent[parent[dish_id]]
            dish_id = parent[dish_id]
        return dish_id
    ordered = sorted(rows.values(), key=lambda row: (row["cafe"], row["timestamp"]))
    mass_maps = {}
    for row in ordered:
        masses = defaultdict(float)
        for ingredient in row["ingredients"]:
            masses[ingredient["ingredient_id"]] += ingredient["mass_g"]
        mass_maps[row["dish_id"]] = {key: value for key, value in masses.items() if value > 0}
    edges = []
    for index, first in enumerate(ordered):
        for second in ordered[index + 1:]:
            elapsed = second["timestamp"] - first["timestamp"]
            if second["cafe"] != first["cafe"] or elapsed > GROUP_WINDOW_SECONDS:
                break
            a, b = mass_maps[first["dish_id"]], mass_maps[second["dish_id"]]
            small, large = (a, b) if len(a) <= len(b) else (b, a)
            if (small.keys() <= large.keys()
                    and all(large[key] + GROUP_MASS_TOLERANCE_G >= value for key, value in small.items())
                    and any(value >= 1 and abs(large[key] - value) <= GROUP_MASS_TOLERANCE_G for key, value in small.items())):
                left, right = find(first["dish_id"]), find(second["dish_id"])
                if left != right:
                    parent[right] = left
                edges.append({"first": first["dish_id"], "second": second["dish_id"], "elapsed_seconds": elapsed})
    groups = defaultdict(list)
    for dish_id in rows:
        groups[find(dish_id)].append(dish_id)
    result = []
    for members in groups.values():
        members.sort()
        identifier = "inferred_plate_" + hashlib.sha256("\n".join(members).encode()).hexdigest()[:20]
        result.append({"group_id": identifier, "members": members, "group_method": "ingredient_mass_time_v1"})
    return sorted(result, key=lambda group: group["group_id"]), edges


def original_split_map():
    result = {}
    for split in ("train", "test"):
        ids = (SOURCE / "dish_ids" / "splits" / f"rgb_{split}_ids.txt").read_text().splitlines()
        for dish_id in ids:
            if dish_id in result:
                raise ValueError("Official train/test overlap: " + dish_id)
            result[dish_id] = split
    return result


def label_quality_issues(row):
    """Source consistency checks fixed before scoring any model predictions.

    These are conservative study QC tolerances, not a claimed physical error
    distribution: five grams or 2% for weighed mass allows scale/rounding noise;
    one kcal or 1% for summed calories allows floating point/recipe rounding.
    Nine kcal/g is the maximum energy density of the three labeled macros;
    the extra margins avoid rejecting decimal rounding at this boundary.
    """
    truth = row["truth"]
    mass = truth["mass_g"]
    calories = truth["calories_kcal"]
    ingredient_mass = sum(item["mass_g"] for item in row["ingredients"])
    ingredient_calories = sum(item["calories_kcal"] for item in row["ingredients"])
    reasons = []
    if all(item["ingredient_id"] == "ingr_0000000423" for item in row["ingredients"]):
        reasons.append("empty_plate_only")
    if all(truth[key] == 0 for key in ("calories_kcal", "fat_g", "carbs_g", "protein_g")) and ingredient_calories > 1:
        reasons.append("zero_dish_nutrient_placeholders_with_positive_ingredient_calories")
    if abs(mass - ingredient_mass) > max(5, 0.02 * mass):
        reasons.append("mass_total_ingredient_sum_mismatch_gt_max_5g_2pct")
    if abs(calories - ingredient_calories) > max(1, 0.01 * calories):
        reasons.append("calories_total_ingredient_sum_mismatch_gt_max_1kcal_1pct")
    if calories > 9 * mass + 5:
        reasons.append("calories_exceed_9kcal_per_g_plus_5kcal")
    if sum(truth[key] for key in ("fat_g", "carbs_g", "protein_g")) > mass + max(2, 0.02 * mass):
        reasons.append("macro_mass_exceeds_total_plus_max_2g_2pct")
    return reasons


def audit_labels():
    rows, invalid = parse_metadata()
    selected_path = DATA / "selection_manifest.jsonl"
    chosen = {row["dish_id"] for row in read_jsonl(selected_path)} if selected_path.exists() else set()
    metrics = {}
    for subset, items in (("all_metadata", list(rows.values())), ("selected", [row for dish_id, row in rows.items() if dish_id in chosen])):
        fields = {}
        for field in ("mass_g", "calories_kcal", "fat_g", "carbs_g", "protein_g"):
            residuals = [abs(row["truth"][field] - sum(item[field] for item in row["ingredients"])) for row in items]
            values = [row["truth"][field] for row in items]
            ordered = sorted(residuals)
            if not values:
                continue
            fields[field] = {"dish_label_min": min(values), "dish_label_max": max(values),
                "dish_label_mean": sum(values) / len(values),
                "ingredient_sum_absolute_residual_max": max(residuals),
                "ingredient_sum_absolute_residual_p95": ordered[int((len(ordered) - 1) * .95)],
                "ingredient_sum_absolute_residual_gt_1": sum(value > 1 for value in residuals),
                "ingredient_sum_absolute_residual_gt_5": sum(value > 5 for value in residuals)}
        metrics[subset] = {"rows": len(items), "fields": fields}
    issues = [{"dish_id": row["dish_id"], "cafe": row["cafe"], "truth": row["truth"],
        "ingredient_totals": {key: sum(item[key] for item in row["ingredients"]) for key in row["truth"]},
        "reasons": label_quality_issues(row)} for row in rows.values() if label_quality_issues(row)]
    dump_jsonl(DATA / "label_quality_exclusions.jsonl", issues)
    summary = {"audited_at_utc": utc_now(), "rules_version": "source_consistency_v2", "invalid_syntax_numeric_rows": len(invalid),
        "source_rows": len(rows), "rejected_unique_rows": len(issues), "eligible_rows": len(rows) - len(issues),
        "rejected_by_cafe": dict(Counter(row["cafe"] for row in issues)),
        "reason_counts_overlap_allowed": dict(Counter(reason for row in issues for reason in row["reasons"])),
        "reason_combinations_disjoint": dict(Counter("|".join(row["reasons"]) for row in issues)),
        "truth_policy": "Use unchanged original dish-level labels after QC. Never synthesize gold from model predictions or replace cafe2 zero totals with inferred totals.",
        "results": metrics}
    dump_json(DATA / "label_quality_audit.json", summary)
    return summary


def prepare(pilot_count=20, blind_count=1000, amend_quality=False):
    """Freeze identity, split, labels, and source before any model evaluation."""
    frozen_path = DATA / "selection_manifest.jsonl"
    prior_manifest = []
    prior_downloads = {}
    if frozen_path.exists() and not amend_quality:
        raise FileExistsError("Selection is already frozen; do not overwrite it after observing model outputs")
    if amend_quality:
        if (DATA / "selection_manifest_v2.jsonl").exists():
            raise FileExistsError("Quality amendment v2 already frozen")
        prior_manifest = read_jsonl(frozen_path)
        prior_downloads = {row["sample_id"]: row for row in read_jsonl(DATA / "manifest.jsonl")}
        archive = DATA / "archive" / "v1_before_quality_audit"
        archive.mkdir(parents=True, exist_ok=False)
        for name in ("selection_manifest.jsonl", "selection_summary.json", "manifest.jsonl", "pilot_manifest.jsonl", "blind_test_manifest.jsonl",
                     "download_validation.json", "groups.jsonl", "group_edges.jsonl", "exclusions.jsonl", "label_quality_audit.json"):
            source_file = DATA / name
            if source_file.exists():
                shutil.copy2(source_file, archive / name)
    rows, exclusions = parse_metadata()
    groups, edges = inferred_groups(rows)
    objects = json.loads((SOURCE / "overhead_rgb_objects.json").read_text())["objects"]
    overhead = {item["key"].split("/")[-2]: item for item in objects}
    splits = original_split_map()
    official_ids = set((SOURCE / "dish_ids" / "dish_ids_all.txt").read_text().splitlines())
    quality_rejected = {dish_id: label_quality_issues(row) for dish_id, row in rows.items() if label_quality_issues(row)}
    for dish_id, reasons in quality_rejected.items():
        exclusions.append({"dish_id": dish_id, "reason": "source_label_quality_failure", "quality_reasons": reasons})
    candidates = {"overhead_rgb": [], "side_camera_A_frame_0": []}
    seen_md5 = {}
    for group in groups:
        eligible = [dish_id for dish_id in group["members"] if dish_id in official_ids and dish_id not in quality_rejected]
        if not eligible:
            exclusions.append({"group_id": group["group_id"], "reason": "no_official_dish_id_with_valid_source_labels"})
            continue
        overhead_ids = [dish_id for dish_id in eligible if dish_id in overhead]
        view = "overhead_rgb" if overhead_ids else "side_camera_A_frame_0"
        dish_id = min(overhead_ids or eligible, key=lambda key: stable_order("representative", key))
        group["representative_dish_id"] = dish_id
        group["representative_view"] = view
        group["original_splits"] = sorted({splits.get(member, "cafe2_unassigned") for member in group["members"]})
        if view == "overhead_rgb":
            md5 = overhead[dish_id]["md5"]
            if md5 in seen_md5:
                exclusions.append({"dish_id": dish_id, "group_id": group["group_id"],
                    "reason": "duplicate_official_image_md5", "duplicate_of": seen_md5[md5]})
                continue
            seen_md5[md5] = dish_id
        candidates[view].append(group)
    for values in candidates.values():
        values.sort(key=lambda group: stable_order("selection", group["group_id"]))
    overhead_groups = candidates["overhead_rgb"]
    side_groups = candidates["side_camera_A_frame_0"]
    required = pilot_count + blind_count
    if len(overhead_groups) + len(side_groups) < required or len(overhead_groups) < pilot_count:
        raise ValueError("Insufficient eligible groups")
    prior_pilot = [row for row in prior_manifest if row["split"] == "pilot"]
    all_prior_pilot_group_ids = {row["group_id"] for row in prior_pilot}
    group_lookup = {group["group_id"]: group for group in groups}
    retained_pilots = []
    for row in prior_pilot:
        if row["dish_id"] not in quality_rejected:
            group = group_lookup[row["group_id"]]
            group["representative_dish_id"] = row["dish_id"]
            group["representative_view"] = row["camera_view"]
            retained_pilots.append(group)
    pilot_groups = list(retained_pilots)
    pilot_groups += [group for group in overhead_groups if group["group_id"] not in all_prior_pilot_group_ids][:pilot_count - len(pilot_groups)]
    pilot_group_ids = {group["group_id"] for group in pilot_groups}
    evaluation_pool = [group for group in overhead_groups + side_groups if group["group_id"] not in pilot_group_ids | all_prior_pilot_group_ids]
    chosen = pilot_groups + evaluation_pool[:blind_count]
    if len(chosen) != required:
        raise ValueError("Insufficient groups after pilot isolation")
    chosen_ids = {group["group_id"] for group in chosen}
    provenance = json.loads((SOURCE / "provenance.json").read_text())
    manifest = []
    for index, group in enumerate(chosen):
        dish_id = group["representative_dish_id"]
        row = rows[dish_id]
        view = group["representative_view"]
        key = (overhead[dish_id]["key"] if view == "overhead_rgb" else PREFIX + f"imagery/side_angles/{dish_id}/camera_A.h264")
        item = {"sample_id": dish_id, "dish_id": dish_id, "group_id": group["group_id"],
            "group_method": "ingredient_mass_time_v1", "group_size": len(group["members"]),
            "split": "pilot" if index < pilot_count else "blind_test",
            "original_split": splits.get(dish_id, "cafe2_unassigned"), "cafe": row["cafe"],
            "image_path": f"data/nutrition5k/images/{dish_id}.png", "camera_view": view,
            "frame_index": None if view == "overhead_rgb" else 0,
            "frame_timestamp_s": None if view == "overhead_rgb" else 0.0,
            "truth": row["truth"], "ingredients": row["ingredients"],
            "metadata_path": row["metadata_path"], "metadata_line": row["metadata_line"],
            "source_url": BUCKET + "/" + key, "source_key": key,
            "license": LICENSE, "license_url": LICENSE_URL,
            "selection_version": 2, "label_validation": "passed_source_consistency_v2",
            "dataset_version": "Nutrition5k-GCS-2021-06-16;README@" + provenance["upstream_commit"],
            "source_object": overhead.get(dish_id) if view == "overhead_rgb" else None,
            "download_status": "pending", "image_sha256": None}
        manifest.append(item)
    for group in groups:
        if group["group_id"] not in chosen_ids:
            exclusions.append({"group_id": group["group_id"], "members": group["members"],
                "reason": "not_selected_by_preregistered_view_priority_and_seed"})
        else:
            for member in group["members"]:
                if member != group["representative_dish_id"]:
                    exclusions.append({"dish_id": member, "group_id": group["group_id"],
                        "reason": "nonrepresentative_incremental_scan_in_selected_group",
                        "representative": group["representative_dish_id"]})
    dump_jsonl(DATA / "groups.jsonl", groups)
    dump_jsonl(DATA / "group_edges.jsonl", edges)
    dump_jsonl(DATA / "exclusions.jsonl", exclusions)
    dump_jsonl(frozen_path, manifest)
    dump_jsonl(DATA / "selection_manifest_v2.jsonl", manifest)
    current_manifest = []
    download_keys = {"download_status", "image_sha256", "image_md5", "image_size_bytes", "image_info", "source_download", "extraction", "download_started_at_utc", "download_finished_at_utc", "source_object"}
    for row in manifest:
        old = prior_downloads.get(row["sample_id"], {})
        current_manifest.append({**row, **{key: value for key, value in old.items() if key in download_keys}})
    dump_jsonl(DATA / "manifest.jsonl", current_manifest)
    dump_jsonl(DATA / "pilot_manifest.jsonl", [row for row in current_manifest if row["split"] == "pilot"])
    dump_jsonl(DATA / "blind_test_manifest.jsonl", [row for row in current_manifest if row["split"] == "blind_test"])
    summary = {"frozen_at_utc": utc_now(), "selection_seed": SEED,
        "selection_manifest_sha256": hashlib.sha256(frozen_path.read_bytes()).hexdigest(),
        "group_window_seconds": GROUP_WINDOW_SECONDS, "group_mass_tolerance_g": GROUP_MASS_TOLERANCE_G,
        "selection_version": 2, "metadata_rows": len(rows), "metadata_invalid_rows": len([x for x in exclusions if "line" in x]),
        "source_quality_rejected_rows": len(quality_rejected), "source_quality_eligible_rows": len(rows) - len(quality_rejected),
        "official_overhead_rgb_objects": len(overhead), "official_overhead_unique_md5": len({item["md5"] for item in objects}),
        "inferred_groups": len(groups), "eligible_overhead_groups": len(overhead_groups),
        "eligible_side_only_groups": len(side_groups),
        "groups_spanning_official_splits": sum(len(group.get("original_splits", [])) > 1 for group in groups),
        "selected": len(manifest), "by_split": dict(Counter(row["split"] for row in manifest)),
        "by_view": dict(Counter(row["camera_view"] for row in manifest)),
        "by_original_split": dict(Counter(row["original_split"] for row in manifest)),
        "strata": dict(Counter(f"{row['split']}|{row['original_split']}|{row['camera_view']}" for row in manifest)),
        "sample_ids_unique": len({row["sample_id"] for row in manifest}) == len(manifest),
        "groups_unique": len({row["group_id"] for row in manifest}) == len(manifest),
        "independence_limit": "Inferred groups, not official physical plate IDs; residual correlation and over-merging are possible.",
        "replacement_policy": "No replacement or favorable-frame selection. Retry identical sources; retain failures in the frozen denominator."}
    if prior_manifest:
        summary["quality_amendment"] = {"reason": "Source-only audit found cafe2 zero nutrient placeholders, inconsistent cafe1 labels, and empty-plate controls before model scoring.",
            "model_scores_consulted": False, "prior_selection_sha256": hashlib.sha256((DATA / "archive/v1_before_quality_audit/selection_manifest.jsonl").read_bytes()).hexdigest(),
            "prior_pilot_rows": len(prior_pilot), "retained_valid_pilot_rows": len(retained_pilots), "additional_pilot_rows": pilot_count - len(retained_pilots),
            "excluded_prior_pilot_ids": [row["dish_id"] for row in prior_pilot if row["dish_id"] in quality_rejected],
            "additional_pilot_ids": [group["representative_dish_id"] for group in pilot_groups if group["group_id"] not in all_prior_pilot_group_ids],
            "prior_pilot_groups_in_evaluation": sorted(all_prior_pilot_group_ids & {row["group_id"] for row in manifest if row["split"] == "blind_test"}),
            "new_evaluation_ids": sorted({row["sample_id"] for row in manifest if row["split"] == "blind_test"} - {row["sample_id"] for row in prior_manifest if row["split"] == "blind_test"})}
    dump_json(DATA / "selection_summary.json", summary)
    audit_labels()
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


def validate_png(blob):
    if blob[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("Not PNG")
    offset, found_end, width, height = 8, False, None, None
    while offset < len(blob):
        length = struct.unpack(">I", blob[offset:offset + 4])[0]
        kind = blob[offset + 4:offset + 8]
        chunk = blob[offset + 8:offset + 8 + length]
        expected_crc = struct.unpack(">I", blob[offset + 8 + length:offset + 12 + length])[0]
        if zlib.crc32(kind + chunk) & 0xffffffff != expected_crc:
            raise ValueError("PNG CRC mismatch")
        if kind == b"IHDR":
            width, height = struct.unpack(">II", chunk[:8])
        if kind == b"IEND":
            found_end = True
            break
        offset += length + 12
    if not found_end or not width or not height:
        raise ValueError("Incomplete PNG")
    return {"width": width, "height": height, "png_crc_valid": True}


def amend_sources():
    """Resolve missing camera-A objects without changing dish, labels, or split.

    The amendment is transparently made after evaluation of other, already
    downloaded samples began. It uses bucket existence metadata only; no model
    response, score, or visually preferred frame is used.
    """
    final_path = DATA / "selection_manifest_v3.jsonl"
    if final_path.exists():
        raise FileExistsError("Source amendment v3 is already frozen")
    original = read_jsonl(DATA / "selection_manifest_v2.jsonl")
    current = {row["sample_id"]: row for row in read_jsonl(DATA / "manifest.jsonl")}
    source_audits = []
    changes = []
    new_selection = []
    started = utc_now()
    for row in original:
        amended = {**row, "selection_version": 3}
        existing = current[row["sample_id"]]
        if row["camera_view"] != "overhead_rgb":
            if existing.get("download_status") == "ok" and existing.get("source_object", {}).get("key") == row["source_key"]:
                amended["source_object"] = existing["source_object"]
            else:
                prefix = PREFIX + f"imagery/side_angles/{row['dish_id']}/"
                available = list_objects(prefix)
                source_audits.append({"dish_id": row["dish_id"], "listed_at_utc": utc_now(), "prefix": prefix, "objects": available})
                by_name = {item["key"].rsplit("/", 1)[-1]: item for item in available}
                preferred = next((by_name[f"camera_{camera}.h264"] for camera in "ABCD" if f"camera_{camera}.h264" in by_name), None)
                if preferred:
                    amended["source_object"] = preferred
                    camera = preferred["key"].rsplit("/", 1)[-1].removeprefix("camera_").removesuffix(".h264")
                    amended["source_key"] = preferred["key"]
                    amended["source_url"] = BUCKET + "/" + preferred["key"]
                    amended["camera_view"] = f"side_camera_{camera}_frame_0"
                    if amended["source_key"] != row["source_key"]:
                        changes.append({"sample_id": row["sample_id"], "dish_id": row["dish_id"], "group_id": row["group_id"],
                            "reason": "Preferred camera_A.h264 object absent from official bucket listing",
                            "old_source_key": row["source_key"], "new_source_key": amended["source_key"],
                            "old_camera_view": row["camera_view"], "new_camera_view": amended["camera_view"],
                            "source_object": preferred, "frame_index": 0, "model_output_consulted": False})
        new_selection.append(amended)
    unchanged_keys = ("sample_id", "dish_id", "group_id", "split", "original_split", "truth", "image_path")
    if any(any(before[key] != after[key] for key in unchanged_keys) for before, after in zip(original, new_selection)):
        raise AssertionError("Source amendment changed sample identity, labels, or split")
    archive = DATA / "archive" / "v2_before_source_resolution"
    archive.mkdir(parents=True, exist_ok=False)
    for name in ("selection_manifest.jsonl", "selection_summary.json", "manifest.jsonl", "pilot_manifest.jsonl", "blind_test_manifest.jsonl", "download_validation.json"):
        shutil.copy2(DATA / name, archive / name)
    changed_ids = {row["sample_id"] for row in changes}
    final_manifest = []
    for row in new_selection:
        existing = current[row["sample_id"]]
        resolved = {**existing, "selection_version": 3, "source_key": row["source_key"], "source_url": row["source_url"],
                    "source_object": row["source_object"], "camera_view": row["camera_view"]}
        if row["sample_id"] in changed_ids:
            for field in ("source_download", "extraction", "image_md5", "image_size_bytes", "image_info", "download_error"):
                resolved.pop(field, None)
            resolved.update({"download_status": "pending", "image_sha256": None})
        final_manifest.append(resolved)
    dump_jsonl(final_path, new_selection)
    dump_jsonl(DATA / "selection_manifest.jsonl", new_selection)
    dump_jsonl(DATA / "manifest.jsonl", final_manifest)
    dump_jsonl(DATA / "pilot_manifest.jsonl", [row for row in final_manifest if row["split"] == "pilot"])
    dump_jsonl(DATA / "blind_test_manifest.jsonl", [row for row in final_manifest if row["split"] == "blind_test"])
    new_hash = hashlib.sha256(final_path.read_bytes()).hexdigest()
    source_amendment = {"started_at_utc": started, "frozen_at_utc": utc_now(), "selection_version": 3,
        "v2_selection_sha256": hashlib.sha256((DATA / "selection_manifest_v2.jsonl").read_bytes()).hexdigest(),
        "v3_selection_sha256": new_hash, "sample_membership_labels_groups_splits_unchanged": True,
        "changes": changes, "changed_source_rows": len(changes), "model_outputs_or_scores_consulted": False,
        "timing_disclosure": "Some verified overhead evaluation calls had begun before this source-only amendment. The data collector did not inspect model responses or scores.",
        "rule": "Keep existing camera A. If absent, use first officially present camera among B,C,D; decode frame index 0. No new dish or preferred-frame replacement.",
        "availability_evidence": source_audits}
    dump_json(DATA / "source_resolution_amendment.json", source_amendment)
    summary = json.loads((DATA / "selection_summary.json").read_text())
    summary.update({"selection_version": 3, "frozen_at_utc": source_amendment["frozen_at_utc"], "selection_manifest_sha256": new_hash,
        "source_resolution_amendment": {key: value for key, value in source_amendment.items() if key not in {"availability_evidence", "changes"}},
        "by_view": dict(Counter(row["camera_view"] for row in new_selection)),
        "strata": dict(Counter(f"{row['split']}|{row['original_split']}|{row['camera_view']}" for row in new_selection))})
    dump_json(DATA / "selection_summary.json", summary)
    print(json.dumps({key: value for key, value in source_amendment.items() if key != "availability_evidence"}, indent=2), flush=True)


def download_one(row, ffmpeg=None, ffmpeg_sha256=None):
    result = dict(row)
    target = ROOT / row["image_path"]
    target.parent.mkdir(parents=True, exist_ok=True)
    started = utc_now()
    try:
        if row["camera_view"] == "overhead_rgb":
            blob = target.read_bytes() if target.exists() else fetch(row["source_url"] + "?generation=" + row["source_object"]["generation"])
            actual = hash_bytes(blob)
            if actual["md5"] != row["source_object"]["md5"] or actual["size_bytes"] != row["source_object"]["size_bytes"]:
                blob = fetch(row["source_url"] + "?generation=" + row["source_object"]["generation"])
                actual = hash_bytes(blob)
                if actual["md5"] != row["source_object"]["md5"] or actual["size_bytes"] != row["source_object"]["size_bytes"]:
                    raise ValueError("Source object hash/size mismatch")
            result["source_download"] = {**actual, "matches_official_md5": True}
            image_info = validate_png(blob)
            publish_bytes(target, blob)
        else:
            if not ffmpeg:
                raise ValueError("--ffmpeg path required for side-video frame extraction")
            object_items = [row["source_object"]] if row.get("source_object") else list_objects(row["source_key"])
            exact = [item for item in object_items if item["key"] == row["source_key"]]
            if len(exact) != 1:
                raise ValueError("Expected side-camera video not available")
            source_object = exact[0]
            result["source_object"] = source_object
            camera_file = row["source_key"].rsplit("/", 1)[-1]
            video = DATA / "videos" / (row["dish_id"] + "_" + camera_file)
            video.parent.mkdir(parents=True, exist_ok=True)
            video_blob = video.read_bytes() if video.exists() else fetch(row["source_url"] + "?generation=" + source_object["generation"])
            video_hash = hash_bytes(video_blob)
            if video_hash["md5"] != source_object["md5"] or video_hash["size_bytes"] != source_object["size_bytes"]:
                video_blob = fetch(row["source_url"] + "?generation=" + source_object["generation"])
                video_hash = hash_bytes(video_blob)
                if video_hash["md5"] != source_object["md5"] or video_hash["size_bytes"] != source_object["size_bytes"]:
                    raise ValueError("Video object hash/size mismatch")
            if not video.exists() or hashlib.md5(video.read_bytes()).hexdigest() != video_hash["md5"]:
                publish_bytes(video, video_blob)
            temporary_image = target.with_name(target.stem + ".partial.png")
            command = [str(ffmpeg), "-hide_banner", "-loglevel", "error", "-y", "-i", str(video),
                       "-vf", "select=eq(n\\,0)", "-frames:v", "1", "-threads", "1", str(temporary_image)]
            completed = subprocess.run(command, capture_output=True, text=True, timeout=120)
            if completed.returncode:
                raise ValueError("ffmpeg frame extraction failed: " + completed.stderr[-1000:])
            blob = temporary_image.read_bytes()
            actual = hash_bytes(blob)
            image_info = validate_png(blob)
            temporary_image.replace(target)
            result["source_download"] = {**video_hash, "matches_official_md5": True, "local_video_path": video.relative_to(ROOT).as_posix()}
            result["extraction"] = {"frame_index": 0, "command_template": "ffmpeg -i SOURCE -vf select=eq(n\\,0) -frames:v 1 -threads 1 TARGET.png",
                "ffmpeg_sha256": ffmpeg_sha256 or hashlib.sha256(Path(ffmpeg).read_bytes()).hexdigest(), "geometric_transforms": "none"}
        result.update({"download_status": "ok", "image_sha256": actual["sha256"], "image_md5": actual["md5"],
                       "image_size_bytes": actual["size_bytes"], "image_info": image_info, "download_started_at_utc": started,
                       "download_finished_at_utc": utc_now()})
        result.pop("download_error", None)
    except Exception as error:
        result.update({"download_status": "failed", "download_error": type(error).__name__ + ": " + str(error),
                       "download_started_at_utc": started, "download_finished_at_utc": utc_now()})
    return result


def download(split=None, workers=8, ffmpeg=None):
    frozen = read_jsonl(DATA / "selection_manifest.jsonl")
    existing = {row["sample_id"]: row for row in read_jsonl(DATA / "manifest.jsonl")}
    selected = [row for row in frozen if not split or row["split"] == split]
    # Manifests are committed, payloads are not. A fresh clone must download
    # rows recorded as ok on the original machine when its local file is absent.
    pending = []
    for row in selected:
        stored = existing[row["sample_id"]]
        path = ROOT / row["image_path"]
        source_video_path = stored.get("source_download", {}).get("local_video_path")
        source_video_missing = row["camera_view"] != "overhead_rgb" and (not source_video_path or not (ROOT / source_video_path).exists())
        if (stored.get("download_status") != "ok" or not path.exists()
                or hashlib.sha256(path.read_bytes()).hexdigest() != stored.get("image_sha256") or source_video_missing):
            pending.append(row)
    ffmpeg_sha256 = hashlib.sha256(Path(ffmpeg).read_bytes()).hexdigest() if ffmpeg else None
    def save():
        manifest = [existing[row["sample_id"]] for row in frozen]
        dump_jsonl(DATA / "manifest.jsonl", manifest)
        dump_jsonl(DATA / "pilot_manifest.jsonl", [row for row in manifest if row["split"] == "pilot"])
        dump_jsonl(DATA / "blind_test_manifest.jsonl", [row for row in manifest if row["split"] == "blind_test"])
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(download_one, row, ffmpeg, ffmpeg_sha256): row for row in pending}
        for count, future in enumerate(concurrent.futures.as_completed(futures), 1):
            result = future.result()
            existing[result["sample_id"]] = result
            if count % 10 == 0 or count == len(pending) or result["download_status"] == "failed":
                save()
                print(f"downloaded {count}/{len(pending)} {result['sample_id']} {result['download_status']}" +
                      (" " + result.get("download_error", "") if result["download_status"] == "failed" else ""), flush=True)
    save()
    validate()


def validate():
    frozen = read_jsonl(DATA / "selection_manifest.jsonl")
    manifest = read_jsonl(DATA / "manifest.jsonl")
    selection_summary = json.loads((DATA / "selection_summary.json").read_text())
    failures = []
    fixed_keys = {key for key in frozen[0] if key not in {"download_status", "image_sha256", "source_object"}}
    hashes = defaultdict(list)
    for expected, row in zip(frozen, manifest):
        if any(expected.get(key) != row.get(key) for key in fixed_keys):
            failures.append({"sample_id": row["sample_id"], "reason": "frozen_selection_modified"})
        if row["download_status"] == "ok":
            blob = (ROOT / row["image_path"]).read_bytes()
            actual = hash_bytes(blob)
            if actual["sha256"] != row["image_sha256"]:
                failures.append({"sample_id": row["sample_id"], "reason": "image_sha256_mismatch"})
            validate_png(blob)
            hashes[actual["sha256"]].append(row["sample_id"])
    duplicates = [ids for ids in hashes.values() if len(ids) > 1]
    frozen_sha = hashlib.sha256((DATA / "selection_manifest.jsonl").read_bytes()).hexdigest()
    summary = {"verified_at_utc": utc_now(), "selection_manifest_sha256": frozen_sha,
        "selection_hash_unchanged": frozen_sha == selection_summary["selection_manifest_sha256"],
        "selected_rows": len(frozen), "manifest_rows": len(manifest), "expected_split_sizes": {"pilot": 20, "blind_test": 1000},
        "status_counts": dict(Counter(row["download_status"] for row in manifest)),
        "status_by_split": dict(Counter(f"{row['split']}|{row['download_status']}" for row in manifest)),
        "downloaded_image_bytes": sum(row.get("image_size_bytes", 0) for row in manifest if row["download_status"] == "ok"),
        "downloaded_source_bytes": sum(row.get("source_download", {}).get("size_bytes", 0) for row in manifest if row["download_status"] == "ok"),
        "unique_sample_ids": len({row["sample_id"] for row in manifest}),
        "unique_inferred_groups": len({row["group_id"] for row in manifest}),
        "unique_downloaded_image_sha256": len(hashes), "duplicate_image_hash_groups": duplicates,
        "validation_failures": failures, "all_complete": all(row["download_status"] == "ok" for row in manifest),
        "all_integrity_checks_pass": not failures and not duplicates and len(frozen) == len(manifest) and frozen_sha == selection_summary["selection_manifest_sha256"]}
    dump_json(DATA / "download_validation.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["fetch-sources", "prepare", "amend-quality", "amend-sources", "audit-labels", "download", "validate"])
    parser.add_argument("--split", choices=["pilot", "blind_test"])
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--ffmpeg", type=Path)
    args = parser.parse_args()
    if args.command == "fetch-sources":
        fetch_sources()
    elif args.command == "prepare":
        prepare()
    elif args.command == "amend-quality":
        prepare(amend_quality=True)
    elif args.command == "amend-sources":
        amend_sources()
    elif args.command == "audit-labels":
        print(json.dumps(audit_labels(), indent=2), flush=True)
    elif args.command == "download":
        download(args.split, args.workers, args.ffmpeg)
    elif args.command == "validate":
        validate()


if __name__ == "__main__":
    main()
