"""Apply a frozen mass calibrator to normalized predictions, without reading labels."""
from pathlib import Path
import argparse
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2] / 'scripts/evaluate'))
from common import read_json, read_jsonl, sha256, write_jsonl
from calibrator import apply_candidates
from be_replay import replay, display_audit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', type=Path, required=True)
    parser.add_argument('--freeze', type=Path, required=True)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--ai-candidates', type=Path, required=True)
    parser.add_argument('--be-workdir', type=Path, help='BE replay files (defaults beside output)')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    freeze = read_json(args.freeze)
    if sha256(args.model.read_bytes()) != freeze['model_sha256'] or sha256((HERE / 'calibrator.py').read_bytes()) != freeze['calibrator_sha256']:
        raise RuntimeError('Frozen model/code mismatch')
    model = read_json(args.model)
    provenance = model['provenance']
    if sha256((HERE / 'be_replay.py').read_bytes()) != provenance['be_replay_sha256']:
        raise RuntimeError('Frozen BE helper mismatch')
    root = HERE.parents[2]
    if sha256((root / 'scripts/evaluate/replay_worker.py').read_bytes()) != provenance['be_worker_sha256'] or sha256((root / 'evaluation/source_index.json').read_bytes()) != provenance['source_index_sha256']:
        raise RuntimeError('Frozen BE replay dependency mismatch')
    rows = read_jsonl(args.input)
    ai = {r['sample_id']: r for r in read_jsonl(args.ai_candidates)}
    if set(ai) != {r['sample_id'] for r in rows}:
        raise RuntimeError('AI candidate IDs mismatch')
    adjusted = [apply_candidates(model, row, ai[row['sample_id']]) for row in rows]
    predictions = list(replay(adjusted, args.be_workdir or args.output.parent / (args.output.stem + '_be_replay')).values())
    write_jsonl(args.output, predictions)
    print({'rows': len(rows), 'applied': sum(r.get('calibration', {}).get('applied', False) for r in predictions),
           'clipped': sum(r.get('calibration', {}).get('clipped', False) for r in predictions),
           'display_contract_audit': display_audit({r['sample_id']: r for r in rows}, {r['sample_id']: r for r in predictions})})


if __name__ == '__main__':
    main()
