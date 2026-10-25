"""Audit and collect unused Nutrition5k groups without model calls or score access.

Writes only this protocol_audit directory and data/nutrition5k_followup.
Gold labels are separate from the model-input manifest. Do not give gold to tuners.
"""
from __future__ import annotations
import argparse
import concurrent.futures
from collections import Counter
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OLD = ROOT / 'data/nutrition5k'
NEW = ROOT / 'data/nutrition5k_followup'
COLLECTOR = ROOT / 'scripts/data/collect_nutrition5k.py'
spec = importlib.util.spec_from_file_location('readonly_existing_collector', COLLECTOR)
collector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(collector)
collector.DATA = NEW
# SOURCE remains the old, immutable source metadata directory. No source-mutating
# collector entry points are called; only parse/QC/list/download_one helpers.

def now():
    return datetime.now(timezone.utc).isoformat()

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def lines(path):
    return [json.loads(x) for x in path.read_text(encoding='utf-8').splitlines() if x.strip()]

def write_json(path, value):
    assert path.resolve().is_relative_to(HERE) or path.resolve().is_relative_to(NEW)
    collector.dump_json(path, value)

def write_lines(path, values):
    assert path.resolve().is_relative_to(HERE) or path.resolve().is_relative_to(NEW)
    collector.dump_jsonl(path, values)

def prepare():
    if (NEW / 'candidate_manifest.jsonl').exists():
        raise FileExistsError('Candidate set already frozen; do not replace it after evaluation.')
    rows, invalid = collector.parse_metadata()
    groups = lines(OLD / 'groups.jsonl')
    selected = lines(OLD / 'selection_manifest_v3.jsonl')
    pilot_v1 = lines(OLD / 'archive/v1_before_quality_audit/pilot_manifest.jsonl')
    old_ids = {x['dish_id'] for x in selected + pilot_v1}
    used_groups = {x['group_id'] for x in selected + pilot_v1}
    official = set((OLD / 'source/dish_ids/dish_ids_all.txt').read_text().splitlines())
    split = collector.original_split_map()
    overhead = {x['key'].split('/')[-2] for x in json.loads((OLD / 'source/overhead_rgb_objects.json').read_text())['objects']}
    rejected = {key for key, row in rows.items() if collector.label_quality_issues(row)}
    saved_rejected = {x['dish_id'] for x in lines(OLD / 'label_quality_exclusions.jsonl')}
    assert not invalid and rejected == saved_rejected
    candidates, gold = [], []
    eligible_groups = []
    for group in groups:
        eligible = [x for x in group['members'] if x in official and x not in rejected]
        if not eligible:
            continue
        eligible_groups.append(group)
        if group['group_id'] in used_groups:
            continue
        assert not (set(group['members']) & old_ids)
        overhead_ids = [x for x in eligible if x in overhead]
        dish = min(overhead_ids or eligible, key=lambda x: collector.stable_order('representative', x))
        assert not overhead_ids, 'Unexpected remaining overhead group; review selection before proceeding.'
        candidates.append({'sample_id': dish, 'dish_id': dish, 'group_id': group['group_id'],
            'group_method': 'ingredient_mass_time_v1', 'group_size': len(group['members']),
            'split': 'followup_holdout', 'original_split': split.get(dish, 'unassigned'),
            'camera_view': 'side_camera_A_frame_0', 'frame_index': 0,
            'image_path': f'data/nutrition5k_followup/images/{dish}.png',
            'source_key': collector.PREFIX + f'imagery/side_angles/{dish}/camera_A.h264',
            'source_url': collector.BUCKET + '/' + collector.PREFIX + f'imagery/side_angles/{dish}/camera_A.h264',
            'source_object': None, 'download_status': 'pending', 'image_sha256': None,
            'license': collector.LICENSE, 'license_url': collector.LICENSE_URL,
            'label_validation': 'passed_source_consistency_v2'})
        gold.append({'sample_id': dish, 'group_id': group['group_id'], 'truth': rows[dish]['truth'],
            'ingredients': rows[dish]['ingredients'], 'metadata_path': rows[dish]['metadata_path'],
            'metadata_line': rows[dish]['metadata_line'],
            'access_rule': 'Scorer only after final hypothesis/code freeze. Never include in model prompt or tuner inputs.'})
    candidates.sort(key=lambda x: x['group_id'])
    gold_lookup = {x['sample_id']: x for x in gold}
    gold = [gold_lookup[x['sample_id']] for x in candidates]
    assert len(candidates) == len({x['sample_id'] for x in candidates}) == len({x['group_id'] for x in candidates})
    assert len(candidates) >= 100
    write_lines(NEW / 'candidate_manifest.jsonl', candidates)
    write_lines(NEW / 'gold_labels.jsonl', gold)
    inputs = [OLD/'groups.jsonl', OLD/'selection_manifest_v3.jsonl', OLD/'label_quality_exclusions.jsonl',
        OLD/'archive/v1_before_quality_audit/pilot_manifest.jsonl', COLLECTOR,
        OLD/'source/metadata/dish_metadata_cafe1.csv', OLD/'source/metadata/dish_metadata_cafe2.csv']
    audit = {'created_at_utc': now(), 'source_metadata_rows': len(rows), 'quality_rejected_rows': len(rejected),
        'eligible_rows': len(rows)-len(rejected), 'all_inferred_groups': len(groups),
        'eligible_groups': len(eligible_groups), 'previous_selected_rows': len(selected),
        'previous_selected_plus_all_v1_pilot_groups': len(used_groups),
        'new_group_count': len(candidates), 'previous_group_overlap': 0, 'previous_dish_overlap': 0,
        'by_official_split': dict(Counter(x['original_split'] for x in candidates)),
        'by_view_before_source_resolution': dict(Counter(x['camera_view'] for x in candidates)),
        'new_1000_disjoint_groups_possible': len(candidates) >= 1000,
        'source_file_availability_verified': False, 'model_outputs_consulted_for_selection': False,
        'candidate_manifest_sha256': sha(NEW/'candidate_manifest.jsonl'), 'gold_sha256': sha(NEW/'gold_labels.jsonl'),
        'input_hashes': {p.relative_to(ROOT).as_posix(): sha(p) for p in inputs},
        'limits': ['Inferred groups do not prove physical plate independence.',
                   'All residual groups are side-camera inputs, unlike the overhead-heavy prior evaluation.',
                   'Public-data model pretraining exposure is unknown.',
                   'Hash/decode checks do not prove visible-food and nutrition-label alignment.']}
    write_json(HERE/'residual_group_audit.json', audit)
    print(json.dumps({k:v for k,v in audit.items() if k not in ('input_hashes',)}, ensure_ascii=False), flush=True)

def resolve():
    target = NEW/'selection_manifest.jsonl'
    if target.exists():
        raise FileExistsError('Source-resolved selection already frozen.')
    candidates = lines(NEW/'candidate_manifest.jsonl')
    def lookup(row):
        prefix = collector.PREFIX + f"imagery/side_angles/{row['dish_id']}/"
        objects = collector.list_objects(prefix)
        by_name = {x['key'].rsplit('/', 1)[-1]: x for x in objects}
        preferred = next((by_name[f'camera_{c}.h264'] for c in 'ABCD' if f'camera_{c}.h264' in by_name), None)
        updated = dict(row)
        if preferred:
            camera = preferred['key'].rsplit('/', 1)[-1][7]
            updated.update(source_object=preferred, source_key=preferred['key'],
                source_url=collector.BUCKET+'/'+preferred['key'], camera_view=f'side_camera_{camera}_frame_0')
        else:
            updated.update(download_status='source_unavailable', download_error='No official camera A/B/C/D object exists')
        return updated, {'sample_id': row['sample_id'], 'listed_at_utc': now(), 'objects': objects}
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        resolved = list(pool.map(lookup, candidates))
    selected, evidence = [x[0] for x in resolved], [x[1] for x in resolved]
    write_lines(target, selected)
    write_lines(NEW/'manifest.jsonl', selected)
    write_json(NEW/'source_availability.json', {'created_at_utc': now(), 'rule':'first existing A,B,C,D; frame 0; no replacements', 'evidence':evidence})
    freeze = {'frozen_at_utc': now(), 'selected': len(selected), 'source_available': sum(x['source_object'] is not None for x in selected),
        'by_camera': dict(Counter(x['camera_view'] for x in selected)), 'by_official_split':dict(Counter(x['original_split'] for x in selected)),
        'selection_manifest_sha256': sha(target), 'gold_sha256':sha(NEW/'gold_labels.jsonl'),
        'source_availability_sha256':sha(NEW/'source_availability.json'), 'candidate_sha256':sha(NEW/'candidate_manifest.jsonl'),
        'label_policy':'gold_labels.jsonl is scorer-only; manifest intentionally omits truth and ingredients',
        'model_calls_made':0, 'no_replacement':True, 'fixed_denominator':len(selected)}
    write_json(NEW/'freeze.json', freeze)
    print(json.dumps(freeze,ensure_ascii=False),flush=True)

def download(workers):
    frozen = lines(NEW/'selection_manifest.jsonl')
    current = {x['sample_id']:x for x in lines(NEW/'manifest.jsonl')}
    ffmpeg = ROOT/'data/downloads/tools/ffmpeg.exe'
    assert ffmpeg.is_file()
    ffmpeg_hash = sha(ffmpeg)
    pending = [x for x in frozen if x['source_object'] is not None and
        (current[x['sample_id']]['download_status'] != 'ok' or not (ROOT/x['image_path']).is_file()
         or sha(ROOT/x['image_path']) != current[x['sample_id']].get('image_sha256')
         or not (ROOT/current[x['sample_id']].get('source_download', {}).get('local_video_path', '__missing__')).is_file())]
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(collector.download_one, x, ffmpeg, ffmpeg_hash): x for x in pending}
        for n, future in enumerate(concurrent.futures.as_completed(futures),1):
            row=future.result(); current[row['sample_id']]=row
            if n%10==0 or n==len(pending) or row['download_status']!='ok':
                write_lines(NEW/'manifest.jsonl',[current[x['sample_id']] for x in frozen])
                print(f"downloaded {n}/{len(pending)} status={row['download_status']}",flush=True)
    write_lines(NEW/'manifest.jsonl',[current[x['sample_id']] for x in frozen])

def validate():
    from PIL import Image
    selected=lines(NEW/'selection_manifest.jsonl'); manifest=lines(NEW/'manifest.jsonl')
    assert {x['sample_id'] for x in selected}=={x['sample_id'] for x in manifest}
    evidence=[]
    for row in manifest:
        if row['download_status']!='ok':
            evidence.append({'sample_id':row['sample_id'],'status':row['download_status']}); continue
        image=ROOT/row['image_path']; video=ROOT/row['source_download']['local_video_path']
        assert sha(image)==row['image_sha256']
        assert sha(video)==row['source_download']['sha256']
        assert hashlib.md5(video.read_bytes()).hexdigest()==row['source_object']['md5']
        with Image.open(image) as img:
            img.load(); rgb=img.convert('RGB'); pixels=hashlib.sha256(rgb.tobytes()).hexdigest(); size=img.size
        evidence.append({'sample_id':row['sample_id'],'status':'ok','size':size,'image_sha256':row['image_sha256'],'pixel_sha256':pixels})
    valid=[x for x in evidence if x['status']=='ok']
    previous_files={x['image_sha256'] for x in lines(OLD/'manifest.jsonl') if x.get('image_sha256')}
    previous_pixels={x['pixel_sha256'] for x in lines(OLD/'image_pixel_audit.jsonl') if x.get('pixel_sha256')}
    prior_audit=json.loads((HERE/'residual_group_audit.json').read_text(encoding='utf-8'))
    unchanged={name:sha(ROOT/name)==expected for name,expected in prior_audit['input_hashes'].items()}
    assert all(unchanged.values()), 'An original input changed during collection.'
    summary={'verified_at_utc':now(),'selected':len(selected),'status_counts':dict(Counter(x['status'] for x in evidence)),
        'file_duplicate_count':len(valid)-len({x['image_sha256'] for x in valid}),
        'pixel_duplicate_count':len(valid)-len({x['pixel_sha256'] for x in valid}),
        'previous_file_hash_overlap':len(previous_files & {x['image_sha256'] for x in valid}),
        'previous_pixel_hash_overlap':len(previous_pixels & {x['pixel_sha256'] for x in valid}),
        'original_inputs_unchanged':unchanged,
        'semantic_food_label_alignment_reviewed':False, 'model_calls':0,
        'manifest_sha256':sha(NEW/'manifest.jsonl'),'selection_sha256':sha(NEW/'selection_manifest.jsonl')}
    write_lines(NEW/'decode_audit.jsonl',evidence); write_json(NEW/'integrity_audit.json',summary)
    freeze=json.loads((NEW/'freeze.json').read_text(encoding='utf-8'))
    freeze.update({'download_verified_at_utc':summary['verified_at_utc'], 'download_manifest_sha256':summary['manifest_sha256'],
        'integrity_audit_sha256':sha(NEW/'integrity_audit.json'), 'download_status_counts':summary['status_counts'],
        'available_by_camera':dict(Counter(x['camera_view'] for x in manifest if x['download_status']=='ok')),
        'confirmation_acceptance':{'minimum_paired_valid':100,'calorie_mae_relative_reduction_min':0.10,
            'paired_delta_bootstrap95_upper_lt':0,'all_selected_within15_rate_must_not_decrease':True,
            'valid_prediction_count_must_not_decrease':True,'confirmation_set_openings':1,
            'accepted_by':'parent coordinator before follow-up candidate evaluation'}})
    write_json(NEW/'freeze.json',freeze)
    print(json.dumps(summary,ensure_ascii=False),flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('command',choices=['prepare','resolve','download','validate']); parser.add_argument('--workers',type=int,default=8)
    args=parser.parse_args()
    if args.command=='download': download(args.workers)
    else: globals()[args.command]()
