"""Offline pinned AI/BE replay and failure-aware follow-up scoring. No API calls.

Confirmation labels are read only when --gold is explicitly supplied.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from pathlib import Path
import re
import statistics
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'scripts/evaluate'))
from common import atomic_json, read_json, read_jsonl, sha256, utc_now, write_jsonl
from metrics import MAPPING, bootstrap_mean_ci, number, percentile, prediction, summarize
from budget import usage_cost


def indexed(rows):
    result = {}
    for row in rows:
        sid = row['sample_id']
        if sid in result:
            raise ValueError(f'Duplicate sample_id: {sid}')
        result[sid] = row
    return result


def join_gold(manifest, path):
    """Deliberately separate label access from replay and inference."""
    labels = indexed(read_jsonl(path))
    selected = {r['sample_id'] for r in manifest}
    if set(labels) != selected:
        raise ValueError('Gold IDs must exactly equal selected manifest IDs')
    return [{**row, 'truth': labels[row['sample_id']]['truth']} for row in manifest]


def paired(manifest, before, after):
    result = {}
    for nutrient, key in MAPPING.items():
        deltas, transitions, old_errors = [], Counter(), []
        for row in manifest:
            sid, truth = row['sample_id'], row['truth'][key]
            old, new = prediction(before.get(sid, {}), nutrient), prediction(after.get(sid, {}), nutrient)
            if number(old) and number(new) and number(truth):
                delta = abs(new - truth) - abs(old - truth)
                deltas.append(delta)
                old_errors.append(abs(old - truth))
                category = 'improved' if delta < -1e-9 else 'worsened' if delta > 1e-9 else 'same_error'
            else:
                category = 'valid_to_missing' if number(old) else 'missing_to_valid' if number(new) else 'both_missing'
            transitions[category] += 1
        old_mae = statistics.fmean(old_errors) if old_errors else None
        delta = statistics.fmean(deltas) if deltas else None
        result[nutrient] = {
            'valid_pair_count': len(deltas), 'transition_counts': dict(transitions),
            'mean_absolute_error_delta_after_minus_before': delta,
            'paired_baseline_mae': old_mae,
            'paired_relative_mae_reduction': -delta / old_mae if old_mae else None,
            'bootstrap_95_percent_ci': bootstrap_mean_ci(deltas),
            'bootstrap_repetitions': 2000, 'positive_delta_means_worse': True,
        }
    return result


def verify_snapshot():
    source = read_json(ROOT / 'evaluation/source_index.json')
    for version, directory in [('improved_ai', ROOT / 'evaluation/tmp/code/improved_ai'),
                               ('improved_be', ROOT / 'evaluation/tmp/code/improved_be')]:
        for relative, expected in source[version]['tracked_files_sha256'].items():
            path = directory / relative
            if not path.is_file() or sha256(path.read_bytes()) != expected:
                raise RuntimeError(f'Pinned source mismatch: {path}')


def replay(arm, args, manifest):
    run = HERE / 'runs' / args.phase / arm
    archive = run / 'responses.jsonl'
    raw = indexed(read_jsonl(archive))
    identity = read_json(run / 'request_freeze.json')
    manifest_hash = sha256(args.manifest.read_bytes())
    if identity['manifest_sha256'] != manifest_hash or identity['arm'] != arm or identity['phase'] != args.phase:
        raise ValueError(f'Run identity mismatch: {arm}')
    selected = {r['sample_id'] for r in manifest}
    if set(raw) - selected:
        raise ValueError(f'Unexpected response IDs: {arm}')
    for row in raw.values():
        if row.get('status') != 'not_attempted' and (
            row.get('request_config_sha256') != identity['request_config_sha256'] or
            row.get('manifest_sha256') != manifest_hash):
            raise ValueError(f'Response identity mismatch: {arm}/{row["sample_id"]}')
    rows = [raw.get(r['sample_id'], {'sample_id': r['sample_id'], 'status': 'not_attempted'}) for r in manifest]
    work = args.output / arm
    work.mkdir(parents=True, exist_ok=True)
    rawpath, aipath, final = work / 'raw.jsonl', work / 'ai.jsonl', work / 'normalized.jsonl'
    write_jsonl(rawpath, rows)
    worker = ROOT / 'scripts/evaluate/replay_worker.py'
    for stage, python, code, inputpath, outputpath in [
        ('ai', ROOT.parent / 'AI/ai-server/venv/Scripts/python.exe', ROOT / 'evaluation/tmp/code/improved_ai/ai-server', rawpath, aipath),
        ('be', ROOT.parent / 'BE/venv/Scripts/python.exe', ROOT / 'evaluation/tmp/code/improved_be', aipath, final),
    ]:
        subprocess.run([str(python), str(worker), '--stage', stage, '--code', str(code),
                        '--input', str(inputpath), '--output', str(outputpath)], cwd=work, check=True)
    latency = [r['latency_ms'] for r in rows if number(r.get('latency_ms'))]
    costs = [usage_cost(r.get('usage')) for r in rows if 'latency_ms' in r]
    usage = [r.get('usage') or {} for r in rows]
    info = {'request_freeze': identity, 'response_archive_sha256': sha256(archive.read_bytes()),
            'collection_status_counts': dict(Counter(r['status'] for r in rows)),
            'model_versions': dict(Counter(r.get('model_version', 'unknown') for r in rows)),
            'latency_ms': {'count': len(latency), 'p50': percentile(latency, .5), 'p95': percentile(latency, .95)},
            'raw_token_totals': {key: sum(u.get(key) or 0 for u in usage) for key in
                                 ('prompt_token_count', 'candidates_token_count', 'thoughts_token_count', 'total_token_count')},
            'usage_present_count': sum(bool(u) for u in usage),
            'usage_estimated_usd_known_only': sum(c for c in costs if c is not None) / 1e9,
            'missing_or_invalid_usage_count': sum(c is None for c in costs),
            'cost_authority': 'experiments/accuracy_followup/cost_ledger.json; missing usage is never zero billed cost'}
    return indexed(read_jsonl(final)), info


def write_csv(path, rows):
    if rows:
        with path.open('w', encoding='utf-8-sig', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase', choices=['dev', 'confirm'], required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--freeze', type=Path, required=True)
    parser.add_argument('--arms', nargs='+', required=True)
    parser.add_argument('--baseline', default='baseline')
    parser.add_argument('--normalized-baseline', type=Path, help='Explicit historical normalized baseline; no new baseline requests')
    parser.add_argument('--gold', type=Path, help='Explicit authorization to read separate labels for scoring')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--reused-baseline', type=Path, help='Optional prior normalized baseline; diagnostic only')
    args = parser.parse_args()
    if any(not re.fullmatch(r'[A-Za-z0-9_-]+', a) for a in [*args.arms, args.baseline]) or (args.baseline not in args.arms and not args.normalized_baseline):
        parser.error('Safe arm names and a baseline included in --arms are required')
    args.manifest, args.freeze = args.manifest.resolve(), args.freeze.resolve()
    args.output = (args.output or HERE / 'results' / args.phase).resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    freeze = read_json(args.freeze)
    manifest_hash = freeze.get('manifest_sha256', freeze.get('selection_manifest_sha256'))
    if sha256(args.manifest.read_bytes()) != manifest_hash:
        raise RuntimeError('Manifest changed')
    manifest = read_jsonl(args.manifest)
    indexed(manifest)
    verify_snapshot()
    versions, transport = {}, {}
    for arm in args.arms:
        versions[arm], transport[arm] = replay(arm, args, manifest)
    historical = None
    if args.normalized_baseline:
        if args.baseline in args.arms:
            parser.error('Historical baseline name must differ from all fresh arms')
        versions[args.baseline] = indexed(read_jsonl(args.normalized_baseline))
        if set(versions[args.baseline]) != {r['sample_id'] for r in manifest}:
            raise RuntimeError('Historical baseline IDs must equal selected manifest')
        historical = {'path': str(args.normalized_baseline), 'sha256': sha256(args.normalized_baseline.read_bytes()),
                      'comparison': 'historical baseline versus newly collected arm; not concurrent model requests',
                      'limitations': 'Same configured model family may have different model revision/timing; prompt and response sampling drift can contribute.',
                      'dev100_drift_diagnostic_reference': str(HERE / 'results/dev/summary.json')}
        for filename in ('request_config.json', 'manifest_freeze.json', 'results/blind_test_no_db_provenance.json'):
            path = ROOT / 'evaluation' / filename
            if path.exists():
                historical[filename] = {'sha256': sha256(path.read_bytes()), 'content': read_json(path)}
        drift = HERE / 'results/dev/summary.json'
        if drift.exists():
            historical['dev100_drift_summary_sha256'] = sha256(drift.read_bytes())
            historical['dev100_reused_vs_fresh_diagnostic'] = read_json(drift).get('reused_vs_fresh_baseline_diagnostic')
        old_archive = ROOT / 'evaluation/evidence/model_responses.jsonl'
        if old_archive.exists():
            ids = {r['sample_id'] for r in manifest}
            old_rows = [r for r in read_jsonl(old_archive) if r.get('sample_id') in ids]
            historical['archived_response_evidence'] = {
                'sha256': sha256(old_archive.read_bytes()), 'selected_rows_found': len(old_rows),
                'model_versions': dict(Counter(r.get('model_version', 'unknown') for r in old_rows))}
    summary = {'generated_at': utc_now(), 'phase': args.phase, 'selected_count': len(manifest),
               'manifest_sha256': manifest_hash,
               'source_index_sha256': sha256((ROOT / 'evaluation/source_index.json').read_bytes()),
               'worker_sha256': sha256((ROOT / 'scripts/evaluate/replay_worker.py').read_bytes()),
               'scorer_sha256': sha256(Path(__file__).read_bytes()), 'transport': transport,
               'protocol_sha256': sha256((HERE / 'protocol.json').read_bytes()),
               'scope': 'Pinned improved AI/BE, no DB/grounding/habits, no live services; all selected rows remain in denominator',
               'exploratory': args.phase == 'dev', 'labels_scored': False,
               'cost_summary_reference': str(HERE / 'cost_summary.json')}
    if historical:
        summary['historical_normalized_baseline'] = historical
    if (HERE / 'cost_summary.json').exists():
        summary['cumulative_cost_snapshot'] = read_json(HERE / 'cost_summary.json')
    if args.gold:
        if freeze.get('gold_sha256') and sha256(args.gold.read_bytes()) != freeze['gold_sha256']:
            raise RuntimeError('Gold hash mismatch')
        manifest = join_gold(manifest, args.gold)
        summary['gold_sha256'] = sha256(args.gold.read_bytes())
    if all('truth' in row for row in manifest):
        summary['labels_scored'] = True
        summary['versions'] = summarize(manifest, versions)
        summary['paired_vs_baseline'] = {arm: paired(manifest, versions[args.baseline], version)
                                         for arm, version in versions.items() if arm != args.baseline}
        summary['strata'] = {field: {value: summarize([r for r in manifest if str(r.get(field)) == value], versions)
                                    for value in sorted({str(r.get(field)) for r in manifest})}
                             for field in ('camera_view', 'original_split')}
        summary['paired_camera_vs_baseline'] = {
            camera: {arm: paired([r for r in manifest if str(r.get('camera_view')) == camera], versions[args.baseline], version)
                     for arm, version in versions.items() if arm != args.baseline}
            for camera in sorted({str(r.get('camera_view')) for r in manifest})}
        if args.reused_baseline:
            reused = indexed(read_jsonl(args.reused_baseline))
            summary['reused_vs_fresh_baseline_diagnostic'] = {
                'source_sha256': sha256(args.reused_baseline.read_bytes()),
                'before': 'reused', 'after': args.baseline,
                'paired': paired(manifest, reused, versions[args.baseline]),
                'versions': summarize(manifest, {'reused': reused, args.baseline: versions[args.baseline]})}
        metric_rows = [{'arm': arm, 'nutrient': nutrient, **metric}
                       for arm, version in summary['versions'].items() for nutrient, metric in version['nutrients'].items()]
        write_csv(args.output / 'metrics.csv', metric_rows)
        cases = []
        for row in manifest:
            for arm, version in versions.items():
                pred = version.get(row['sample_id'], {})
                case = {'sample_id': row['sample_id'], 'arm': arm, 'status': pred.get('status', 'missing')}
                for nutrient, key in MAPPING.items():
                    value, truth = prediction(pred, nutrient), row['truth'][key]
                    case.update({f'truth_{nutrient}': truth, f'prediction_{nutrient}': value,
                                 f'absolute_error_{nutrient}': abs(value - truth) if number(value) else None})
                cases.append(case)
        write_csv(args.output / 'cases.csv', cases)
        baseline = summary['versions'][args.baseline]['nutrients']['calories']
        gate_name = 'dev_advancement_screen' if args.phase == 'dev' else 'confirmation_acceptance'
        summary[gate_name] = {}
        if args.phase == 'dev':
            summary['development_screen_scope'] = ('Predeclared advancement prescreen applies to development100 only.'
                ' For full development1000 these repeated checks are descriptive diagnostics, not a newly added selection or confirmation gate.')
        criteria = read_json(HERE / 'protocol.json')['confirmation']
        for arm in summary['paired_vs_baseline']:
            metric = summary['versions'][arm]['nutrients']['calories']
            pair = summary['paired_vs_baseline'][arm]['calories']
            reduction = pair['paired_relative_mae_reduction']
            checks = {'within_15_percent_all_selected_not_decreased': metric['within_15_percent_count'] >= baseline['within_15_percent_count'],
                      'valid_prediction_count_not_decreased': metric['valid_prediction_count'] >= baseline['valid_prediction_count']}
            if args.phase == 'dev':
                checks['paired_calorie_mae_reduction_gt_5_percent'] = reduction is not None and reduction > .05
                summary[gate_name][arm] = {'eligible': all(checks.values()), 'checks': checks, 'paired_relative_mae_reduction': reduction}
            else:
                overall_reduction = (1 - metric['mae'] / baseline['mae']) if baseline['mae'] and metric['mae'] is not None else None
                ci = pair['bootstrap_95_percent_ci']
                checks.update({'minimum_paired_valid_100': pair['valid_pair_count'] >= criteria['minimum_paired_valid'],
                               'calorie_mae_reduction_at_least_10_percent': overall_reduction is not None and overall_reduction >= criteria['calorie_mae_relative_reduction_minimum'],
                               'paired_calorie_mae_reduction_at_least_10_percent': reduction is not None and reduction >= criteria['calorie_mae_relative_reduction_minimum'],
                               'paired_bootstrap_95_ci_upper_negative': ci is not None and ci[1] < 0})
                summary[gate_name][arm] = {'accepted': all(checks.values()), 'checks': checks,
                                          'overall_relative_mae_reduction': overall_reduction,
                                          'paired_relative_mae_reduction': reduction,
                                          'criteria': criteria, 'single_frozen_comparison_required': True}
    atomic_json(args.output / 'summary.json', summary)
    if summary['labels_scored']:
        snapshot = {'phase': args.phase, 'selected_count': len(manifest), 'scorer_sha256': summary['scorer_sha256'],
                    'protocol_sha256': summary['protocol_sha256'], 'exploratory': summary['exploratory'],
                    'versions': {name: {nutrient: {key: version['nutrients'][nutrient][key] for key in
                                                   ('mae', 'valid_prediction_count', 'within_15_percent_count')}
                                         for nutrient in ('calories', 'mass_g')} for name, version in summary['versions'].items()},
                    'paired_calories': {name: value['calories'] for name, value in summary['paired_vs_baseline'].items()},
                    'camera_metrics': {camera: {name: {nutrient: {key: version['nutrients'][nutrient][key] for key in
                                                                 ('selected_count', 'valid_prediction_count', 'mae', 'within_15_percent_count')}
                                                       for nutrient in ('calories', 'mass_g')} for name, version in values.items()}
                                       for camera, values in summary['strata']['camera_view'].items()},
                    'historical_baseline_comparison': bool(historical), 'acceptance_or_screen': summary[gate_name],
                    'development_screen_scope': summary.get('development_screen_scope'),
                    'cumulative_cost_snapshot': summary.get('cumulative_cost_snapshot')}
        atomic_json(args.output / 'report_snapshot.json', snapshot)
    print(str(args.output / 'summary.json'))


if __name__ == '__main__':
    main()
