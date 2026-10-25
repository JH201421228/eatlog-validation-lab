"""Bounded follow-up experiment requests; inputs are images and frozen prompts only."""
from __future__ import annotations
import argparse
import asyncio
import json
import mimetypes
from pathlib import Path
import re
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'scripts/evaluate'))
from common import atomic_json, canonical, image_path, read_json, read_jsonl, sha256, utc_now, write_jsonl
from budget import BudgetError, Ledger, process_lock
from collect import api_key


async def run(args):
    from google import genai
    from google.genai import types
    config = read_json(args.arm_dir / 'request_config.json')
    if config['model'] != 'gemini-2.5-flash' or config['max_output_tokens'] != 4096:
        raise RuntimeError('Unapproved model or output bound')
    if config.get('thinking_budget', 0) not in (0, 512, 1024):
        raise RuntimeError('Unsupported thinking budget')
    prompt = (args.arm_dir / 'prompt.txt').read_text(encoding='utf-8')
    schema = read_json(args.arm_dir / 'response_schema.json')
    if sha256(prompt.encode()) != config['prompt_sha256'] or sha256(canonical(schema)) != config['schema_sha256']:
        raise RuntimeError('Prompt/schema hash mismatch')
    frozen = read_json(args.freeze)
    if sha256(args.manifest.read_bytes()) != frozen['manifest_sha256']:
        raise RuntimeError('Selection changed')
    # Copy only routing fields; labels, ingredients and truth never enter requests.
    rows = [{'sample_id': r['sample_id'], 'image_path': r['image_path']}
            for r in read_jsonl(args.manifest)]
    if len({r['sample_id'] for r in rows}) != len(rows):
        raise RuntimeError('Duplicate sample IDs')
    downloads = {r['sample_id']: {k: r.get(k) for k in ('image_path', 'image_sha256', 'download_status')}
                 for r in read_jsonl(args.download_manifest)}
    outdir = HERE / 'runs' / args.phase / args.arm
    outdir.mkdir(parents=True, exist_ok=True)
    identity = {'arm': args.arm, 'phase': args.phase, 'manifest_sha256': frozen['manifest_sha256'],
                'request_config_sha256': sha256(canonical(config)), 'model': config['model'],
                'prompt_sha256': config['prompt_sha256'], 'schema_sha256': config['schema_sha256'],
                'code_sha256': sha256(Path(__file__).read_bytes()), 'selected_count': len(rows)}
    freeze_path = outdir / 'request_freeze.json'
    if freeze_path.exists():
        previous = read_json(freeze_path)
        if any(previous[k] != identity[k] for k in identity if k != 'code_sha256'):
            raise RuntimeError('Run identity changed; use a new arm name')
    else:
        atomic_json(freeze_path, {**identity, 'frozen_at': utc_now()})
    ledger = Ledger(HERE / 'cost_ledger.json')
    semaphore, stop = asyncio.Semaphore(args.concurrency), asyncio.Event()
    errors = 0
    client = genai.Client(api_key=api_key(), http_options=types.HttpOptions(
        timeout=90000, retry_options=types.HttpRetryOptions(attempts=1)))
    generation = types.GenerateContentConfig(response_mime_type='application/json',
        response_json_schema=schema, temperature=0, seed=config['seed'], max_output_tokens=4096,
        thinking_config=types.ThinkingConfig(thinking_budget=config.get('thinking_budget', 0)))
    async def one(row):
        nonlocal errors
        async with semaphore:
            sid = row['sample_id']
            if not re.fullmatch(r'[A-Za-z0-9_-]+', sid):
                raise ValueError('Unsafe sample ID')
            request_id = f'followup_{args.phase}_{args.arm}_{sid}'
            target = outdir / f'{sid}.json'
            if target.exists() or request_id in ledger.data['entries'] or stop.is_set():
                return
            path = image_path(row)
            source = downloads.get(sid, {})
            if source.get('download_status') != 'ok' or not path.is_file():
                print(json.dumps({'sample_id': sid, 'status': 'source_unavailable'}), flush=True)
                return
            binary = path.read_bytes()
            if source.get('image_path') != row['image_path'] or sha256(binary) != source.get('image_sha256'):
                raise RuntimeError('Image hash mismatch')
            result = {'sample_id': sid, 'request_id': request_id, 'started_at': utc_now(),
                      'arm': args.arm, 'phase': args.phase, 'image_sha256': sha256(binary),
                      'request_config_sha256': identity['request_config_sha256'],
                      'manifest_sha256': identity['manifest_sha256']}
            contents = [prompt, types.Part.from_bytes(data=binary, mime_type=mimetypes.guess_type(path.name)[0] or 'image/png')]
            try:
                counted = await client.aio.models.count_tokens(model=config['model'], contents=contents)
                upper = int(counted.total_tokens) + len(canonical(schema)) + 4096
                result['counted_input_tokens'] = counted.total_tokens
                if upper > 20000:
                    raise BudgetError('Input bound exceeded')
            except Exception as exc:
                result.update(status='count_tokens_failed', error_type=type(exc).__name__)
                atomic_json(target, result)
                errors += 1
                if errors >= 3 or isinstance(exc, BudgetError):
                    stop.set()
                return
            if stop.is_set():
                return
            digest = sha256(canonical({'config': identity['request_config_sha256'], 'image': sha256(binary)}))
            result['request_sha256'] = digest
            try:
                ledger.reserve(request_id, digest)
            except BudgetError:
                stop.set()
                return
            started, usage = time.perf_counter(), None
            try:
                response = await client.aio.models.generate_content(model=config['model'], contents=contents, config=generation)
                usage = response.usage_metadata.model_dump(mode='json') if response.usage_metadata else None
                result.update(status='response_received', raw_text=response.text or '', usage=usage,
                              model_version=response.model_version,
                              finish_reason=str(response.candidates[0].finish_reason) if response.candidates else None)
                errors = 0
                if usage and ((usage.get('prompt_token_count') or 0) > 20000 or
                              (usage.get('candidates_token_count') or 0) + (usage.get('thoughts_token_count') or 0) > 4096):
                    result['token_bound_violation'] = True
                    stop.set()
            except Exception as exc:
                result.update(status='generation_failed', error_type=type(exc).__name__)
                errors += 1
                if errors >= 3:
                    stop.set()
            finally:
                result.update(latency_ms=round((time.perf_counter()-started)*1000, 2), completed_at=utc_now())
                atomic_json(target, result)
                ledger.settle(request_id, usage, result['status'])
                atomic_json(HERE / 'cost_summary.json', ledger.summary())
            print(json.dumps({'arm': args.arm, 'sample_id': sid, 'status': result['status'],
                              'cumulative_usd': ledger.summary()['charged_or_reserved_usd']}), flush=True)
    try:
        await asyncio.gather(*(one(row) for row in rows))
    finally:
        await client.aio.aclose()
        client.close()
        atomic_json(HERE / 'cost_summary.json', ledger.summary())
        records = [read_json(outdir / f"{r['sample_id']}.json") if (outdir / f"{r['sample_id']}.json").exists()
                   else {'sample_id': r['sample_id'], 'status': 'not_attempted'} for r in rows]
        write_jsonl(outdir / 'responses.jsonl', records)
    print(json.dumps({'selected': len(rows), 'stopped': stop.is_set(), **ledger.summary()}), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--arm-dir', type=Path, required=True)
    parser.add_argument('--arm', required=True)
    parser.add_argument('--phase', choices=['dev', 'confirm'], required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--freeze', type=Path, required=True)
    parser.add_argument('--download-manifest', type=Path, required=True)
    parser.add_argument('--concurrency', type=int, default=4)
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]+', args.arm) or not 1 <= args.concurrency <= 4:
        parser.error('Invalid arm or concurrency')
    if not (HERE / 'cost_ledger.json').exists():
        parser.error('Run prepare_followup.py first; prior expenses must be inherited')
    with process_lock(ROOT / 'evaluation/tmp/collector.lock'):
        asyncio.run(run(args))


if __name__ == '__main__':
    main()
