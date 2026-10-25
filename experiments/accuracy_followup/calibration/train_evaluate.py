"""Exploratory log/linear mass ridge families on previously observed main1000."""
from __future__ import annotations
import argparse
from collections import Counter
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / 'scripts/evaluate'))
from common import atomic_json, canonical, read_jsonl, sha256, utc_now, write_jsonl
from metrics import number, prediction, summarize
from calibrator import ALPHAS, FEATURE_NAMES, apply_candidates, feature_input, features, fit
from be_replay import replay, display_audit

BINS = {'low_lt150g': lambda m: m < 150, 'middle_150_to400g': lambda m: 150 <= m < 400, 'high_ge400g': lambda m: m >= 400}
FAMILY_RULE = {
    'origin': 'Additional exploratory family and candidate screen requested after observing high-mass deterioration; not a reviewer-prescribed rule',
    'alpha_within_family': 'lowest OOF mass MAE among 10,100,1000; tie lowest alpha',
    'family_selection': 'lowest overall OOF calorie MAE among eligible families',
    'eligibility': 'mass and calorie MAE both improve, all-selected calorie within15 count and valid coverage do not decrease; when truthmass>=400g selected group n>=30, calorie MAE worsening must not exceed 10%',
    'linear_negative_prediction': 'retain original mass/candidates for nonpositive mass, otherwise fixed factor clipping [0.5,2]',
    'weighted_log_mass': 'Final additional development loss hypothesis after log/linear high-mass failures; weight=clip(train truthmass/median(train truthmass),0.5,4); weights never used in inference',
}


def candidate_screen(report):
    metrics = report['winner_oof_metrics']
    raw, new = (metrics[k]['nutrients'] for k in ('raw', 'learned_oof'))
    high = report['truth_mass_bins_diagnostic_only']['high_ge400g']
    oldhigh, newhigh = (high[k]['nutrients']['calories'] for k in ('raw', 'learned_oof'))
    high_n = oldhigh['selected_count']
    high_ratio = newhigh['mae'] / oldhigh['mae'] if oldhigh['mae'] else None
    checks = {'mass_mae_improves': new['mass_g']['mae'] < raw['mass_g']['mae'],
              'calorie_mae_improves': new['calories']['mae'] < raw['calories']['mae'],
              'calorie_within15_count_not_decreased': new['calories']['within_15_percent_count'] >= raw['calories']['within_15_percent_count'],
              'calorie_valid_prediction_count_not_decreased': new['calories']['valid_prediction_count'] >= raw['calories']['valid_prediction_count'],
              'high_mass_calorie_mae_worsening_at_most_10_percent_when_n_ge30': high_n < 30 or (high_ratio is not None and high_ratio <= 1.10)}
    return {'eligible': all(checks.values()), 'checks': checks, 'high_mass_group_selected_n': high_n,
            'high_mass_paired_valid_n': report['diagnostic_high_mass_counts']['paired_valid'],
            'high_mass_calorie_mae_ratio_learned_over_raw': high_ratio}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, default=ROOT / 'data/nutrition5k/selection_manifest_v3.jsonl')
    parser.add_argument('--predictions', type=Path, default=ROOT / 'evaluation/results/blind_test_improved_no_db.jsonl')
    parser.add_argument('--ai-candidates', type=Path, default=ROOT / 'evaluation/tmp/replay_blind_test_no_db/improved_ai.jsonl')
    parser.add_argument('--output', type=Path, default=HERE / 'results_families')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    manifest = [r for r in read_jsonl(args.manifest) if r['split'] == 'blind_test']
    raw = {r['sample_id']: r for r in read_jsonl(args.predictions)}
    ai = {r['sample_id']: r for r in read_jsonl(args.ai_candidates)}
    if set(ai) != set(raw) or len(manifest) != 1000 or set(raw) != {r['sample_id'] for r in manifest}:
        raise RuntimeError('Expected matching prior main1000 IDs')
    folds = {r['sample_id']: int(sha256(('mass-calibration-fold-v1|' + r['group_id']).encode()), 16) % 5 for r in manifest}
    eligible = [r for r in manifest if features(feature_input(raw[r['sample_id']])) is not None and number(r['truth']['mass_g']) and r['truth']['mass_g'] > 0]
    x = {r['sample_id']: features(feature_input(raw[r['sample_id']])) for r in eligible}
    all_candidates = [c for row in ai.values() for c in (row.get('candidates') or [])]
    provenance = {'generated_at': utc_now(), 'manifest_sha256': sha256(args.manifest.read_bytes()),
                  'predictions_sha256': sha256(args.predictions.read_bytes()), 'ai_candidates_sha256': sha256(args.ai_candidates.read_bytes()),
                  'calibrator_sha256': sha256((HERE / 'calibrator.py').read_bytes()), 'trainer_sha256': sha256(Path(__file__).read_bytes()),
                  'be_replay_sha256': sha256((HERE / 'be_replay.py').read_bytes()),
                  'be_worker_sha256': sha256((ROOT / 'scripts/evaluate/replay_worker.py').read_bytes()),
                  'source_index_sha256': sha256((ROOT / 'evaluation/source_index.json').read_bytes()),
                  'fit_rows': len(eligible), 'selected_rows': len(manifest), 'target': 'truth.mass_g only as training target',
                  'alternative_label_audit': {'candidate_count': len(all_candidates),
                                              'package_nonnull_candidates': sum(c.get('package') is not None for c in all_candidates),
                                              'label_nonnull_candidates': sum(c.get('label') is not None for c in all_candidates),
                                              'plate_protection': 'Any non-null package/label among all alternatives prevents whole-plate correction'},
                  'feature_source': 'normalized model output only; no truth labels/ingredients/IDs/camera/dates',
                  'application': 'Scale candidate estimated_serving_g only; preserve count/unit/density; actual pinned BE arithmetic/rounding',
                  'split_only_metadata': 'group_id SHA256 modulo 5; group disjoint; standardization fitted on fold training only',
                  'regularization_candidates': ALPHAS, 'feature_names': FEATURE_NAMES, 'factor_bounds_predeclared': [.5, 2.],
                  'feature_rules': {'zero_kcal_log_density_floor_kcal_per_g': 1e-6, 'count': 'known count sum plus availability fraction',
                                    'korean_ngrams': 'SHA256 signed 64 buckets, lengths 2/3, food mass weighting'},
                  'training_features_sha256': sha256(canonical([x[r['sample_id']] for r in eligible])),
                  'fold_sizes_all_selected': dict(Counter(folds.values()))}
    families = {}
    for family in ('log_mass', 'linear_mass', 'weighted_log_mass'):
        directory = args.output / family
        directory.mkdir(parents=True, exist_ok=True)
        alpha_reports, oof_versions = {}, {}
        for alpha in ALPHAS:
            adjusted = dict(ai)
            for fold in range(5):
                train = [r for r in eligible if folds[r['sample_id']] != fold]
                test = [r for r in eligible if folds[r['sample_id']] == fold]
                model = fit([x[r['sample_id']] for r in train], [r['truth']['mass_g'] for r in train], alpha, family)
                for row in test:
                    sid = row['sample_id']
                    adjusted[sid] = apply_candidates(model, raw[sid], ai[sid])
            oof = replay([adjusted[r['sample_id']] for r in manifest], directory / f'replay_alpha_{alpha}')
            alpha_reports[str(alpha)] = {'metrics': summarize(manifest, {'raw': raw, 'learned_oof': oof}),
                                        'applied_count': sum(r.get('calibration', {}).get('applied', False) for r in oof.values()),
                                        'clipped_count': sum(r.get('calibration', {}).get('clipped', False) for r in oof.values()),
                                        'negative_or_nonfinite_fallback_count': sum(r.get('calibration', {}).get('fallback', False) for r in oof.values()),
                                        'display_contract_audit': display_audit(raw, oof)}
            oof_versions[alpha] = oof
        winner = min(ALPHAS, key=lambda a: (alpha_reports[str(a)]['metrics']['learned_oof']['nutrients']['mass_g']['mae'], a))
        model = fit([x[r['sample_id']] for r in eligible], [r['truth']['mass_g'] for r in eligible], winner, family)
        loss = {'log_mass': 'squared error in log grams', 'linear_mass': 'squared error in grams',
                'weighted_log_mass': 'weighted squared error in log grams; training mass weights [0.5,4], weighted centering and unregularized intercept'}[family]
        model['provenance'] = {**provenance, 'family': family, 'loss': loss, 'family_rule': FAMILY_RULE}
        atomic_json(directory / 'model.json', model)
        oof = oof_versions[winner]
        write_jsonl(directory / 'oof_predictions.jsonl', [oof[r['sample_id']] for r in manifest])
        versions = {'raw': raw, 'learned_oof': oof}
        report = {'family': family, 'provenance': model['provenance'], 'selected_alpha': winner, 'all_alphas': alpha_reports,
                  'winner_oof_metrics': summarize(manifest, versions),
                  'diagnostic_high_mass_counts': {
                      'selected': sum(r['truth']['mass_g'] >= 400 for r in manifest),
                      'paired_valid': sum(r['truth']['mass_g'] >= 400 and
                                          number(prediction(raw[r['sample_id']], 'calories')) and
                                          number(prediction(oof[r['sample_id']], 'calories')) for r in manifest)},
                  'truth_mass_bins_diagnostic_only': {name: summarize([r for r in manifest if predicate(r['truth']['mass_g'])], versions) for name, predicate in BINS.items()}}
        report['candidate_screen'] = candidate_screen(report)
        families[family] = report
        atomic_json(directory / 'report.json', report)
        atomic_json(directory / 'freeze.json', {'frozen_at': utc_now(), 'model_sha256': sha256((directory / 'model.json').read_bytes()),
                                              **{k: provenance[k] for k in ('manifest_sha256', 'predictions_sha256', 'calibrator_sha256', 'trainer_sha256')}})
        print(family, 'alpha', winner, 'candidate', report['candidate_screen'], flush=True)
        print({v: {k: round(m['nutrients'][k]['mae'], 6) for k in ('mass_g', 'calories')} for v, m in report['winner_oof_metrics'].items()}, flush=True)
    accepted = [name for name, report in families.items() if report['candidate_screen']['eligible']]
    selected = min(accepted, key=lambda name: families[name]['winner_oof_metrics']['learned_oof']['nutrients']['calories']['mae']) if accepted else None
    report = {'provenance': provenance, 'exploratory': True, 'confirmation_labels_opened': False, 'additional_api_calls': 0,
              'family_selection_rule': FAMILY_RULE, 'selected_family': selected, 'families': families,
              'limitations': ['All main1000 outcomes previously observed; alpha/family CV selection has optimism.',
                             'Linear target was added after observing large-portion deterioration; this is development iteration.',
                             'Inferred grouping does not establish physical independence.',
                             'Correction depends on external VLM composition/density; overhead photos may not transfer to side cameras/Korean traffic.',
                             'Truth mass strata are diagnostic/candidate-screen only, never inference features/routing.']}
    atomic_json(args.output / 'report.json', report)
    snapshot = {'generated_at': utc_now(), 'exploratory': True, 'selected_family': selected,
                'fit_rows': len(eligible), 'selected_rows': len(manifest),
                'family_rule': FAMILY_RULE, 'provenance': provenance, 'families': {}}
    for family, result in families.items():
        def concise(metrics):
            return {version: {nutrient: {key: row['nutrients'][nutrient][key] for key in
                                        ('mae', 'valid_prediction_count', 'within_15_percent_count')}
                              for nutrient in ('mass_g', 'calories')} for version, row in metrics.items()}
        alpha = str(result['selected_alpha'])
        snapshot['families'][family] = {'selected_alpha': result['selected_alpha'],
                                        'overall': concise(result['winner_oof_metrics']),
                                        'by_truth_mass_diagnostic_only': {key: concise(value) for key, value in result['truth_mass_bins_diagnostic_only'].items()},
                                        'candidate_screen': result['candidate_screen'],
                                        'clipped_count': result['all_alphas'][alpha]['clipped_count'],
                                        'negative_fallback_count': result['all_alphas'][alpha]['negative_or_nonfinite_fallback_count'],
                                        'display_contract_audit': result['all_alphas'][alpha]['display_contract_audit']}
    atomic_json(args.output / 'report_snapshot.json', snapshot)
    print('selected_family', selected, 'fit_rows', len(eligible))


if __name__ == '__main__':
    main()
