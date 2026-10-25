"""Run the two frozen confirmation arms concurrently with ONE budget ledger.

The existing collectors stay byte-for-byte unchanged. Their Ledger constructor
is dependency-injected to return the same durable, locked object. One process
owns the budget OS lock and each arm has two in-flight requests (four total).
No gold labels are read; both arms use the exact frozen image-only manifest.
"""
from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
from types import SimpleNamespace
import json
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / 'scripts/evaluate'))
from budget import Ledger, process_lock
from common import read_json, sha256
import run_model
import run_model_compare


async def collect():
    freeze = read_json(HERE / 'candidate_freeze.json')
    if freeze['candidate_policy'] != 'flash35_minimal' or freeze['confirmation_gold_opened']:
        raise RuntimeError('Unexpected or already-scored confirmation policy')
    for relative, digest in freeze['frozen_files_sha256'].items():
        if sha256((ROOT / relative).read_bytes()) != digest:
            raise RuntimeError('Frozen input/code changed: ' + relative)
    ledger_path = HERE / 'cost_ledger.json'
    if not ledger_path.is_file():
        raise RuntimeError('Inherited cost ledger is missing; collection prohibited')
    if sha256(ledger_path.read_bytes()) != freeze['prior_ledger_sha256']:
        raise RuntimeError('Inherited cost ledger changed; automatic resume prohibited')
    ledger = Ledger(ledger_path)
    # Each collector executes the same reserve/settle methods on this object.
    # No collector creates an independent in-memory copy that could lose costs.
    original_factories = run_model.Ledger, run_model_compare.Ledger
    run_model.Ledger = run_model_compare.Ledger = lambda path: ledger
    common = dict(phase='confirm', manifest=ROOT / 'data/nutrition5k_followup/selection_manifest.jsonl',
                  freeze=HERE / 'confirmation_input_freeze.json',
                  download_manifest=ROOT / 'data/nutrition5k_followup/manifest.jsonl', concurrency=2)
    baseline = SimpleNamespace(**common, arm='baseline', arm_dir=HERE / 'baseline')
    candidate = SimpleNamespace(**common, arm='flash35_minimal', arm_dir=HERE / 'model_comparison/flash35_minimal')
    try:
        results = await asyncio.gather(run_model.run(baseline), run_model_compare.run(candidate), return_exceptions=True)
        failures = [type(value).__name__ for value in results if isinstance(value, BaseException)]
        print(json.dumps({'all_collectors_returned_without_unhandled_error': not failures, 'errors': failures,
                          'maximum_combined_concurrency': 4, **ledger.summary()}), flush=True)
        if failures:
            raise RuntimeError('At least one collector failed; records and reservations retained')
    finally:
        run_model.Ledger, run_model_compare.Ledger = original_factories


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    with process_lock(ROOT / 'evaluation/tmp/collector.lock'):
        asyncio.run(collect())


if __name__ == '__main__':
    main()
