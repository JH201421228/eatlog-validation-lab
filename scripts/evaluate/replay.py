"""Replay the exact same raw model responses through two pinned AI/BE versions."""
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

from common import ROOT, EVAL, atomic_json, read_json, read_jsonl, sample_id, sha256, utc_now, write_jsonl


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=["pilot", "blind_test"], required=True)
    parser.add_argument("--manifest", type=Path, default=ROOT / "data/nutrition5k/selection_manifest.jsonl")
    parser.add_argument("--freeze", type=Path, default=EVAL / "manifest_freeze.json")
    parser.add_argument("--response-archive", type=Path, default=EVAL / "evidence/model_responses.jsonl")
    parser.add_argument("--nutrition-snapshot", type=Path)
    args = parser.parse_args()
    freeze = read_json(args.freeze)
    if sha256(args.manifest.read_bytes()) != freeze["manifest_sha256"]:
        raise RuntimeError("Manifest changed")
    manifest = [r for r in read_jsonl(args.manifest) if r["split"] == args.split]
    archive = {r["sample_id"]: r for r in read_jsonl(args.response_archive)} if args.response_archive.exists() else {}
    rows = []
    for row in manifest:
        identifier = sample_id(row)
        rawpath = EVAL / f"raw_responses/{identifier}.json"
        raw = read_json(rawpath) if rawpath.exists() else archive.get(identifier, {"sample_id": identifier, "status": "not_attempted"})
        if raw.get("status") != "not_attempted" and raw.get("request_config_sha256") != freeze["request_config_sha256"]:
            raise RuntimeError("Raw response came from a different request configuration")
        rows.append(raw)
    suffix = "with_db" if args.nutrition_snapshot else "no_db"
    work = EVAL / "tmp" / f"replay_{args.split}_{suffix}"
    work.mkdir(parents=True, exist_ok=True)
    rawfile = work / "raw.jsonl"
    write_jsonl(rawfile, rows)
    worker = Path(__file__).with_name("replay_worker.py")
    for version in ("baseline", "improved"):
        aipath = EVAL / "tmp/code" / f"{version}_ai" / "ai-server"
        bepath = EVAL / "tmp/code" / f"{version}_be"
        aifile = work / f"{version}_ai.jsonl"
        final = EVAL / "results" / f"{args.split}_{version}_{suffix}.jsonl"
        commands = [
            [str(ROOT.parent / "AI/ai-server/venv/Scripts/python.exe"), str(worker), "--stage", "ai", "--code", str(aipath), "--input", str(rawfile), "--output", str(aifile)],
            [str(ROOT.parent / "BE/venv/Scripts/python.exe"), str(worker), "--stage", "be", "--code", str(bepath), "--input", str(aifile), "--output", str(final)],
        ]
        if args.nutrition_snapshot:
            commands[1] += ["--nutrition-snapshot", str(args.nutrition_snapshot)]
        for command in commands:
            subprocess.run(command, cwd=work, check=True)
    atomic_json(EVAL / "results" / f"{args.split}_{suffix}_provenance.json", {
        "replayed_at": utc_now(), "manifest_sha256": freeze["manifest_sha256"], "rows": len(rows),
        "source_index_sha256": sha256((EVAL / "source_index.json").read_bytes()),
        "response_archive_sha256": sha256(args.response_archive.read_bytes()) if args.response_archive.exists() else None,
        "nutrition_snapshot_sha256": sha256(args.nutrition_snapshot.read_bytes()) if args.nutrition_snapshot else None,
        "grounding": False, "habit_correction": False, "count_half_steps": False,
        "selection": "highest confidence among retained candidates per food_index, then sum all food groups",
        "scope": "Pinned AI normalization and BE nutrition resolution; not end-to-end production traffic",
    })


if __name__ == "__main__":
    main()
