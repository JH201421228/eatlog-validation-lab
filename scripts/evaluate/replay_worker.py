"""Isolated pinned-code worker. Network is replaced at the transport boundary.

AI and BE both use an `app` package, so each version/stage has its own process.
This worker contains no API key handling and makes no live service/DB requests.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import math
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from common import read_jsonl, write_jsonl

NUTRIENTS = ("calories", "carbs", "protein", "fat")


def finite(value):
    return isinstance(value, (float, int)) and not isinstance(value, bool) and math.isfinite(value)


def raw_prediction(text):
    """Direct model estimate; no normalization, DB, labels or count corrections."""
    try:
        data = json.loads(text)
        raw = data["candidates"]
        if not isinstance(raw, list):
            return {"status": "invalid_candidates"}
        groups = {}
        for candidate in raw:
            if not isinstance(candidate, dict):
                return {"status": "invalid_candidate"}
            key = (candidate.get("image_index", 0), candidate.get("is_in_image", True), candidate.get("food_index", 0))
            groups.setdefault(key, []).append(candidate)
        if not groups:
            return {"status": "no_candidates"}
        selected = [max(group, key=lambda c: c.get("confidence", 0) if finite(c.get("confidence", 0)) else 0)
                    for group in groups.values()]
        totals = dict.fromkeys(NUTRIENTS, 0.0)
        mass = 0.0
        for candidate in selected:
            grams = candidate.get("estimated_serving_g")
            density = candidate.get("nutrition_per_100g")
            if not finite(grams) or grams <= 0 or not isinstance(density, dict):
                return {"status": "incomplete_nutrition", "food_groups": len(selected)}
            if any(not finite(density.get(k)) or density[k] < 0 for k in NUTRIENTS):
                return {"status": "invalid_nutrition", "food_groups": len(selected)}
            for nutrient in NUTRIENTS:
                totals[nutrient] += density[nutrient] * grams / 100
            mass += grams
        return {"status": "success", "totals": {**totals, "mass_g": mass}, "food_groups": len(selected)}
    except (ValueError, TypeError, KeyError):
        return {"status": "invalid_json"}


async def ai_stage(rows):
    from app.services import vision
    output = []
    for row in rows:
        result = {"sample_id": row["sample_id"], "collection_status": row["status"]}
        if row["status"] != "response_received":
            result.update(status="failed", reason=row["status"], candidates=[])
        else:
            response = SimpleNamespace(text=row.get("raw_text", ""))
            with patch.object(vision, "_download_image", AsyncMock(return_value=(b"mock-transport-image", "image/png"))), \
                 patch.object(vision.gemini_client, "generate_json", AsyncMock(return_value=response)), \
                 patch.object(vision.product_lookup, "attach_labels", AsyncMock(return_value=None)):
                try:
                    replayed = await vision.analyze("https://evaluation.example/image.png", candidate_depth="standard")
                    result.update({k: replayed[k] for k in ("status", "reason", "candidates") if k in replayed})
                except Exception as exc:
                    result.update(status="failed", reason="normalizer_exception", error_type=type(exc).__name__, candidates=[])
            result["raw_model_prediction"] = raw_prediction(row.get("raw_text", ""))
        output.append(result)
    return output


def be_stage(rows, snapshot):
    from app.ai_client.base import AICandidate
    from app.services.analyze import _grouped_candidates, resolve_nutrition
    from app.services.matching import normalize_name, _match_priority
    by_name = {}
    if snapshot:
        for row in read_jsonl(snapshot):
            if not str(row.get("external_id") or "").startswith("rep:"):
                by_name.setdefault(row["normalized_name"], []).append(SimpleNamespace(**row))
    output = []
    for row in rows:
        result = {"sample_id": row["sample_id"], "ai_status": row["status"],
                  "raw_model_prediction": row.get("raw_model_prediction")}
        if row["status"] != "success":
            result.update(status="failed", reason=row.get("reason", "ai_failed"))
            output.append(result)
            continue
        try:
            candidates = [AICandidate.model_validate(c) for c in row["candidates"]]
            grouped = {}
            for index, candidate in _grouped_candidates(candidates):
                grouped.setdefault(index, []).append(candidate)
            # FE candidateGroups.js sorts each capped group by confidence_score.
            picked = [max(group, key=lambda c: c.confidence) for group in grouped.values()]
            totals = dict.fromkeys(NUTRIENTS, 0.0)
            mass = 0.0
            details = []
            complete = True
            mass_complete = True
            for candidate in picked:
                matched_rows = by_name.get(normalize_name(candidate.food_name), [])
                matched = min(matched_rows, key=_match_priority) if matched_rows else None
                resolved = resolve_nutrition(candidate, matched)
                detail = {"food_name": candidate.food_name, "confidence": candidate.confidence,
                          "grams": resolved.grams, "count": resolved.count, "count_unit": resolved.count_unit,
                          "estimated_serving": resolved.estimated_serving, "source": resolved.source,
                          "matched_nutrition_id": matched.id if matched else None,
                          "package_present": candidate.package is not None,
                          "printed_kcal": candidate.package.printed_kcal if candidate.package else None,
                          "package_size_g": candidate.package.size_g if candidate.package else None,
                          "grounded_label_present": candidate.label is not None,
                          "nutrition_per_unit": resolved.nutrition.model_dump() if resolved.nutrition else None}
                if resolved.nutrition is None:
                    complete = False
                else:
                    for nutrient in NUTRIENTS:
                        amount = getattr(resolved.nutrition, nutrient) * resolved.estimated_serving
                        if not finite(amount) or amount < 0:
                            complete = False
                        else:
                            totals[nutrient] += amount
                if finite(resolved.grams) and resolved.grams > 0:
                    mass += resolved.grams
                else:
                    mass_complete = False
                details.append(detail)
            result.update(status="success" if complete and picked else "incomplete_nutrition",
                          food_groups=len(picked), selected=details,
                          normalized_candidate_count=len(candidates),
                          totals={**totals, "mass_g": mass if mass_complete else None} if complete and picked else None)
        except Exception as exc:
            result.update(status="failed", reason="be_replay_exception", error_type=type(exc).__name__)
        output.append(result)
    return output


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=["ai", "be"], required=True)
    parser.add_argument("--code", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--nutrition-snapshot", type=Path)
    args = parser.parse_args()
    sys.path.insert(0, str(args.code.resolve()))
    os.environ["DATABASE_URL"] = "sqlite://"
    os.environ["GEMINI_API_KEY"] = ""
    os.environ["COUNT_HALF_STEPS"] = "false"
    logging.disable(logging.CRITICAL)
    rows = read_jsonl(args.input)
    results = asyncio.run(ai_stage(rows)) if args.stage == "ai" else be_stage(rows, args.nutrition_snapshot)
    write_jsonl(args.output, results)
    print(json.dumps({"stage": args.stage, "rows": len(results), "success": sum(r["status"] == "success" for r in results)}))


if __name__ == "__main__":
    main()
