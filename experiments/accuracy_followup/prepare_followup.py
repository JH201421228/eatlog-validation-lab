"""Freeze development routing and inherit, never reset, the authorized budget."""
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'scripts/evaluate'))
from common import atomic_json, canonical, read_json, read_jsonl, sha256, utc_now, write_jsonl


def main():
    HERE.mkdir(parents=True, exist_ok=True)
    original = ROOT / 'evaluation/cost_ledger.json'
    target = HERE / 'cost_ledger.json'
    if not target.exists():
        shutil.copyfile(original, target)
        atomic_json(HERE / 'budget_inheritance.json', {
            'created_at': utc_now(), 'source': 'evaluation/cost_ledger.json',
            'source_sha256': sha256(original.read_bytes()),
            'prior_summary': read_json(ROOT / 'evaluation/cost_summary.json'),
            'total_authorized_usd': 30,
            'rule': 'All previous entries remain charged/reserved. Only this follow-up collector may spend further.'})
    rows = [r for r in read_jsonl(ROOT / 'data/nutrition5k/selection_manifest_v3.jsonl') if r['split'] == 'blind_test']
    # Membership is determined by IDs, not errors, confidence, food type or labels.
    selected = sorted(rows, key=lambda r: sha256(('followup-dev-v1|' + r['sample_id']).encode()))[:100]
    path = HERE / 'dev100_manifest.jsonl'
    if path.exists():
        if [r['sample_id'] for r in read_jsonl(path)] != [r['sample_id'] for r in selected]:
            raise RuntimeError('Development membership changed')
    else:
        write_jsonl(path, selected)
    atomic_json(HERE / 'dev100_freeze.json', {
        'manifest_sha256': sha256(path.read_bytes()), 'count': len(selected),
        'selection_rule': 'Lowest SHA256(followup-dev-v1|sample_id), 100 from previous main1000',
        'purpose': 'Exploration only; original outcomes were already observed',
        'prior_main1000_all_exploratory': True,
        'source_manifest_sha256': sha256((ROOT / 'data/nutrition5k/selection_manifest_v3.jsonl').read_bytes())})
    base = HERE / 'baseline'
    base.mkdir(exist_ok=True)
    for name in ('prompt.txt', 'response_schema.json', 'request_config.json'):
        if not (base / name).exists():
            shutil.copyfile(ROOT / 'evaluation' / name, base / name)
    print('Frozen dev100 and inherited budget; no API calls.')


if __name__ == '__main__':
    main()
