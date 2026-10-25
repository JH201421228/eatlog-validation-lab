"""Independent final arithmetic/provenance review; never calls a model or service."""
from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def rows(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]


def main():
    manifest_path = ROOT / "data/nutrition5k/selection_manifest_v3.jsonl"
    selected = [row for row in rows(manifest_path) if row["split"] == "blind_test"]
    summary = read_json(ROOT / "evaluation/results/blind_test_no_db_summary.json")
    ledger = read_json(ROOT / "evaluation/cost_ledger.json")
    checks = []

    def check(name, condition, **detail):
        checks.append({"name": name, "passed": bool(condition), **detail})

    check("selection_count", len(selected) == 1000, actual=len(selected))
    identifiers = {row["sample_id"] for row in selected}
    check("unique_selected_samples", len(identifiers) == 1000)
    digest = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    check("summary_uses_final_manifest", summary["manifest_sha256"] == digest, sha256=digest)

    estimates = {}
    for version in ("baseline", "improved"):
        path = ROOT / f"evaluation/results/blind_test_{version}_no_db.jsonl"
        records = rows(path)
        predicted = {row["sample_id"]: row for row in records}
        check(version + "_contains_every_selected_sample_once", len(records) == 1000 and set(predicted) == identifiers)
        errors, apes, within = [], [], 0
        for sample in selected:
            result = predicted.get(sample["sample_id"], {})
            value = (result.get("totals") or {}).get("calories")
            if result.get("status") != "success" or type(value) not in (int, float) or not math.isfinite(value):
                continue
            truth = sample["truth"]["calories_kcal"]
            absolute_error = abs(value - truth)
            errors.append(absolute_error)
            if truth != 0:
                apes.append(100 * absolute_error / abs(truth))
            within += absolute_error <= .15 * abs(truth)
        measured = {
            "valid_prediction_count": len(errors),
            "missing_prediction_count": 1000 - len(errors),
            "mae": sum(errors) / len(errors) if errors else None,
            "mape_percent": sum(apes) / len(apes) if apes else None,
            "within_15_percent_count": within,
            "within_15_percent_of_all_selected": within / 10,
        }
        reported = summary["versions"][version]["nutrients"]["calories"]
        for key, value in measured.items():
            actual = reported[key]
            equal = actual is None if value is None else actual is not None and math.isclose(actual, value, rel_tol=1e-9, abs_tol=1e-9)
            check(version + "_" + key, equal, independently_computed=value, reported=actual)
        estimates[version] = {"metrics": measured, "status_counts": dict(Counter(row["status"] for row in records))}

    entries = list(ledger["entries"].values())
    reserved = sum(row["charged_or_reserved_nanos"] for row in entries)
    settled = [row for row in entries if row["state"] == "usage_settled"]
    direct_usage_cost = sum((row["usage"]["prompt_token_count"] * 300
                            + (row["usage"]["candidates_token_count"]
                               + (row["usage"].get("thoughts_token_count") or 0)) * 2500)
                           for row in settled)
    check("settled_usage_cost_matches_ledger", direct_usage_cost == sum(row["charged_or_reserved_nanos"] for row in settled))
    check("settled_plus_unresolved_reservations_within_30_usd", reserved <= 30_000_000_000, usd=reserved / 1_000_000_000)
    check("no_request_still_reserved_without_terminal_outcome", all(row.get("outcome") for row in entries))

    audit = {
        "reviewed_at_utc": datetime.now(timezone.utc).isoformat(),
        "method": "Independent standard-library arithmetic over fixed dish labels and saved replay totals; no evaluation metric helper imported.",
        "scope": "Calorie aggregation arithmetic, final selection coverage, and cost ledger; this is not an independent nutrition annotation or validation of model pretraining exposure.",
        "all_checks_pass": all(check["passed"] for check in checks),
        "checks": checks,
        "independent_estimates": estimates,
        "cost": {"generations_attempted": len(entries), "usage_estimated_usd": direct_usage_cost / 1_000_000_000,
                 "settled_plus_unresolved_reserved_usd": reserved / 1_000_000_000,
                 "billing_invoice_verified": False},
    }
    destination = ROOT / "review/final_audit.json"
    destination.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"all_checks_pass": audit["all_checks_pass"], "checks": len(checks), "cost": audit["cost"]}))
    if not audit["all_checks_pass"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
