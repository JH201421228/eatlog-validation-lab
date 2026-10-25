"""Freeze all prior main1000 as development routing, with no API calls."""
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / 'scripts/evaluate'))
from common import atomic_json, read_json, read_jsonl, sha256, write_jsonl


def main():
    source = ROOT / 'data/nutrition5k/selection_manifest_v3.jsonl'
    rows = [r for r in read_jsonl(source) if r['split'] == 'blind_test']
    if len(rows) != 1000 or len({r['sample_id'] for r in rows}) != 1000:
        raise RuntimeError('Expected exactly 1000 distinct prior blind_test rows')
    path = HERE / 'dev1000_manifest.jsonl'
    if path.exists():
        if read_jsonl(path) != rows:
            raise RuntimeError('Existing development manifest differs')
    else:
        write_jsonl(path, rows)
    freeze = {'manifest_sha256': sha256(path.read_bytes()), 'count': 1000,
              'source_manifest_sha256': sha256(source.read_bytes()),
              'selection_rule': 'All original selection_v3 blind_test rows in original order',
              'purpose': 'Exploratory full development; all previous main1000 outcomes observed',
              'collection': '1000 fresh neutral requests; dev100 responses intentionally not reused; approximately 100 duplicate requests',
              'new_arm': 'neutral_full'}
    target = HERE / 'dev1000_freeze.json'
    if target.exists():
        if read_json(target) != freeze:
            raise RuntimeError('Existing development freeze differs')
    else:
        atomic_json(target, freeze)
    print(freeze)


if __name__ == '__main__':
    main()
