"""Summarize frozen OOF predictions by camera, without changing fit or gates."""
from pathlib import Path
import argparse
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / 'scripts/evaluate'))
from common import atomic_json, read_jsonl, sha256, utc_now
from metrics import summarize


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, default=ROOT / 'data/nutrition5k/selection_manifest_v3.jsonl')
    parser.add_argument('--raw', type=Path, default=ROOT / 'evaluation/results/blind_test_improved_no_db.jsonl')
    parser.add_argument('--family-root', type=Path, default=HERE / 'results_families')
    args = parser.parse_args()
    rows = [r for r in read_jsonl(args.manifest) if r.get('split') == 'blind_test']
    if len(rows) != 1000:
        raise RuntimeError('This diagnostic is restricted to prior development1000')
    ids = {r['sample_id'] for r in rows}
    versions = {'raw': {r['sample_id']: r for r in read_jsonl(args.raw)}}
    provenance = {'manifest_sha256': sha256(args.manifest.read_bytes()), 'raw_sha256': sha256(args.raw.read_bytes())}
    for family in ('log_mass', 'linear_mass', 'weighted_log_mass'):
        path = args.family_root / family / 'oof_predictions.jsonl'
        versions[family] = {r['sample_id']: r for r in read_jsonl(path)}
        provenance[family + '_oof_sha256'] = sha256(path.read_bytes())
    if any(set(predictions) != ids for predictions in versions.values()):
        raise RuntimeError('Prediction IDs mismatch')
    strata = {camera: summarize([r for r in rows if r['camera_view'] == camera], versions)
              for camera in sorted({r['camera_view'] for r in rows})}
    report = {'generated_at': utc_now(), 'provenance': provenance, 'exploratory_diagnostic_only': True,
              'no_fitting_or_new_acceptance_gate': True, 'camera_view': strata,
              'limitation': 'Development camera strata are observed development results; they do not establish transfer to the separate side-camera confirmation groups.'}
    atomic_json(args.family_root / 'camera_diagnostic.json', report)
    snapshot = {camera: {name: {nutrient: {key: version['nutrients'][nutrient][key]
                                         for key in ('selected_count', 'valid_prediction_count', 'mae', 'within_15_percent_count')}
                                for nutrient in ('mass_g', 'calories')} for name, version in value.items()} for camera, value in strata.items()}
    atomic_json(args.family_root / 'camera_diagnostic_snapshot.json', snapshot)
    print(snapshot)


if __name__ == '__main__':
    main()
