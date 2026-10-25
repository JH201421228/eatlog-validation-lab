"""Pinned BE transport replay and display-contract checks, with no live services."""
import copy
from pathlib import Path
import re
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / 'scripts/evaluate'))
from common import read_json, read_jsonl, sha256, write_jsonl


def replay(rows, directory):
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    code = ROOT / 'evaluation/tmp/code/improved_be'
    index = read_json(ROOT / 'evaluation/source_index.json')['improved_be']
    for name, digest in index['tracked_files_sha256'].items():
        if sha256((code / name).read_bytes()) != digest:
            raise RuntimeError('Pinned BE source mismatch')
    ai, be = directory / 'adjusted_ai.jsonl', directory / 'be.jsonl'
    write_jsonl(ai, rows)
    subprocess.run([str(ROOT.parent / 'BE/venv/Scripts/python.exe'), str(ROOT / 'scripts/evaluate/replay_worker.py'),
                    '--stage', 'be', '--code', str(code), '--input', str(ai), '--output', str(be)], check=True, cwd=directory)
    result = read_jsonl(be)
    metadata = {r['sample_id']: r.get('calibration', {'applied': False}) for r in rows}
    for row in result:
        row['calibration'] = metadata[row['sample_id']]
    return {r['sample_id']: r for r in result}


def display_audit(before, after):
    count_changes, serving_mismatches, base_mass_mismatches = [], [], []
    checked = 0
    for sid, row in after.items():
        if row.get('status') != 'success':
            continue
        old = before[sid].get('selected') or []
        new = row.get('selected') or []
        if [(f.get('food_name'), f.get('count'), f.get('count_unit')) for f in old] != [(f.get('food_name'), f.get('count'), f.get('count_unit')) for f in new]:
            count_changes.append(sid)
        for food in new:
            if food.get('count') and food.get('estimated_serving') != food['count']:
                serving_mismatches.append(sid)
            base = (food.get('nutrition_per_unit') or {}).get('base_serving', '')
            match = re.search(r'\(([0-9]+(?:\.[0-9]+)?)g\)', base)
            if match and food.get('grams'):
                checked += 1
                expected = food['grams'] / (food.get('count') or 1.)
                if abs(float(match.group(1)) - expected) > max(1e-3, abs(expected) * 1e-5):
                    base_mass_mismatches.append(sid)
    return {'observed_count_or_unit_changes': sorted(set(count_changes)),
            'count_vs_estimated_serving_mismatches': sorted(set(serving_mismatches)),
            'base_serving_mass_checked_foods': checked,
            'base_serving_mass_mismatches': sorted(set(base_mass_mismatches))}
