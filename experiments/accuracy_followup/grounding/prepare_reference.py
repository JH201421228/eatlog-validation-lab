"""Build an allowlisted public reference with current importer, never a DB session."""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from grounding import quality_reason

HERE = Path(__file__).resolve().parent
LAB = HERE.parents[2]
EXPECTED_SOURCE_SHA = "5161faa96a5250b2465188f377ddf3021a5dd15a39127ba6ba524ba9b86652c5"
FIELDS = ("name", "normalized_name", "base_amount", "base_unit", "calories", "carbs", "protein", "fat",
          "source", "external_id", "macros_estimated", "serving_basis", "is_representative")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def write_jsonl(path, rows):
    path.write_text("".join(json.dumps(r, ensure_ascii=False, allow_nan=False) + "\n" for r in rows), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--be", type=Path, default=LAB.parent / "BE")
    args = parser.parse_args()
    be = args.be.resolve()
    os.environ["DATABASE_URL"] = "sqlite://"
    os.environ["GEMINI_API_KEY"] = ""
    logging.disable(logging.CRITICAL)
    sys.path.insert(0, str(be))
    from scripts.import_mfds_material import load, build_generics, generic_keys, _is_part, _last_token

    source = be / "scripts/data/mfds_material.jsonl"
    assert sha(source) == EXPECTED_SOURCE_SHA, "New source version requires a new protocol"
    members, excluded = load(source)
    generics = build_generics(members)
    groups = defaultdict(list)
    result = []
    for raw, value in members:
        row = {key: value.get(key) for key in FIELDS}
        row.update(reference_type="variant", source_food_codes=[raw["foodCd"]],
                   source_category=raw.get("foodLv3Nm"), source_state=raw.get("foodLv7Nm"),
                   source_levels=[raw.get(f"foodLv{i}Nm", "") for i in (4, 5, 6)],
                   generic_keys=generic_keys(raw), provenance={
                       "source_name": raw.get("srcNm"), "production_method": raw.get("dataProdNm"),
                       "production_date": raw.get("crtYmd"), "reference_date": raw.get("crtrYmd"),
                       "source_basis": raw.get("nutConSrtrQua"),
                   })
        result.append(row)
        for ext, name in generic_keys(raw):
            if " " not in name and any(_is_part(raw.get(f"foodLv{lv}Nm") or "") for lv in ("5", "6")):
                continue
            groups[ext].append((raw, value))
    for ext, value in generics.items():
        group = groups[ext]
        chosen = [r for r in group if _last_token(r[0].get("foodNm", "")) == "생것"]
        chosen = chosen or [r for r in group if _last_token(r[0].get("foodNm", "")) == "평균"] or group
        chosen = [(r, v) for r, v in chosen if v["base_unit"] == value["base_unit"]]
        row = {key: value.get(key) for key in FIELDS}
        row.update(reference_type="current_generic", source_food_codes=[r["foodCd"] for r, _ in chosen],
                   provenance={"aggregation": "current importer raw > average > all; arithmetic mean",
                               "source_count": len(chosen)})
        result.append(row)
    for i, row in enumerate(result, 1):
        row["id"] = i
        row["quality_rejection"] = quality_reason(row)
    target = HERE / "reference.jsonl"
    write_jsonl(target, result)
    raw_rows = [json.loads(line) for line in source.read_text(encoding="utf-8").splitlines()]
    included = {r["foodCd"] for r, _ in members}
    seen = set()
    excluded_rows = []
    for row in raw_rows:
        code = row.get("foodCd")
        reason = "duplicate_food_code" if code in seen else "current_importer_rejection" if code not in included else None
        if reason:
            excluded_rows.append({"food_code": code, "food_name": row.get("foodNm"), "reason": reason})
        seen.add(code)
    write_jsonl(HERE / "reference_exclusions.jsonl", excluded_rows)
    audit = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_file": "BE/scripts/data/mfds_material.jsonl", "source_sha256": sha(source),
        "source_bytes": source.stat().st_size, "source_rows": len(raw_rows),
        "unique_food_codes": len(seen), "variants": len(members), "current_generics": len(generics),
        "importer_exclusions": dict(excluded), "reference_sha256": sha(target),
        "quality_rejection_counts": dict(Counter(r["quality_rejection"] for r in result)),
        "source_names": dict(Counter(r.get("srcNm") for r, _ in members)),
        "source_production_methods": dict(Counter(r.get("dataProdNm") for r, _ in members)),
        "public_api_endpoint_without_key": "https://api.data.go.kr/openapi/tn_pubr_public_nutri_material_info_api",
        "official_dataset_page": "https://www.data.go.kr/data/15100065/standard.do",
        "production_db_opened": False, "network_requests": 0, "mock_seed_used": False,
        "code_sha256": {str(p.relative_to(be)).replace('\\', '/'): sha(p) for p in [
            be / "scripts/import_mfds_material.py", be / "scripts/import_mfds_api.py",
            be / "scripts/import_public_nutrition.py", be / "app/services/matching.py",
            be / "app/services/analyze.py"]},
    }
    write_json(HERE / "reference_audit.json", audit)
    print(json.dumps({k: audit[k] for k in ("variants", "current_generics", "importer_exclusions", "quality_rejection_counts")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
