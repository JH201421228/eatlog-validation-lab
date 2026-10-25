"""Freeze a bounded current-model comparison before any new-model results."""
from pathlib import Path
import hashlib
import json

HERE = Path(__file__).resolve().parent
BASE = HERE / 'baseline'
ARM = HERE / 'model_comparison' / 'flash35_minimal'


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def main():
    ARM.mkdir(parents=True, exist_ok=True)
    for name in ('prompt.txt', 'response_schema.json'):
        (ARM / name).write_bytes((BASE / name).read_bytes())
    config = json.loads((BASE / 'request_config.json').read_text(encoding='utf-8'))
    config.pop('thinking_budget')
    config.update(model='gemini-3.5-flash-lite', thinking_level='MINIMAL',
                  pricing_input_usd_per_million=0.30, pricing_output_usd_per_million=2.50,
                  pricing_source='https://ai.google.dev/gemini-api/docs/pricing',
                  pricing_checked_date='2026-10-25',
                  one_generation_replayed_for_both_versions=False)
    save(ARM / 'request_config.json', config)
    source = (HERE / 'run_model.py').read_text(encoding='utf-8')
    source = source.replace("config['model'] != 'gemini-2.5-flash'", "config['model'] != 'gemini-3.5-flash-lite'")
    source = source.replace("if config.get('thinking_budget', 0) not in (0, 512, 1024):", "if config.get('thinking_level') != 'MINIMAL' or config.get('pricing_input_usd_per_million') != .30 or config.get('pricing_output_usd_per_million') != 2.50:")
    source = source.replace("thinking_budget=config.get('thinking_budget', 0)", "thinking_level=config['thinking_level']")
    source = source.replace("ledger = Ledger(HERE / 'cost_ledger.json')", "ledger = Ledger(HERE / 'cost_ledger.json')\n    ledger.data['contains_multiple_models'] = True\n    ledger.data['pricing_note'] = 'Inherited 2.5 Flash and 3.5 Flash-Lite use identical standard 0.30/2.50 USD per million token rates; each run freezes model/config separately.'")
    source = source.replace("frozen['manifest_sha256']", "frozen.get('manifest_sha256', frozen.get('selection_manifest_sha256'))")
    (HERE / 'run_model_compare.py').write_text(source, encoding='utf-8')
    protocol_path = HERE / 'protocol.json'
    protocol = json.loads(protocol_path.read_text(encoding='utf-8'))
    protocol['external_model_comparison_amendment'] = {
        'before_new155_labels_opened': True,
        'reason': 'Review asks for periodic external-model comparison. Initial four arms varied prompt/thinking but used a single model. Add one bounded current low-cost model comparison before final selection.',
        'arm': 'gemini-3.5-flash-lite, minimal thinking; exact original baseline prompt/schema, temperature0, seed20260722, maxoutput4096',
        'dataset': 'Same frozen development100; fresh baseline_v1 reference. Exploratory only.',
        'screen': 'Same >5% paired calorie MAE improvement, no lower valid count or all-selected within15 count. If it passes, evaluate frozen arm on old1000 before any confirmation; no new prompt tuning for this model.',
        'deployment': 'Still requires one frozen final policy comparison on new155 and original confirmation gates. Never choose a per-case oracle model using truth.',
        'cost': 'Same standard input0.30/output2.50 USD per million including thoughts; shared inherited US$30 ledger; no search/grounding/cache/tools/retries.',
        'sources': [config['pricing_source'], 'https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite', 'https://ai.google.dev/gemini-api/docs/thinking'],
        'checked_date': '2026-10-25',
        'availability': 'Model listing describes stable model. API count-token failures or unsupported settings stop without automatic generation retries; record failures instead of substituting models.'
    }
    save(protocol_path, protocol)
    save(ARM.parent / 'freeze.json', {
        'model': config['model'], 'configuration_sha256': hashlib.sha256((ARM / 'request_config.json').read_bytes()).hexdigest(),
        'runner_sha256': hashlib.sha256((HERE / 'run_model_compare.py').read_bytes()).hexdigest(),
        'selection_sha256': hashlib.sha256((HERE / 'dev100_manifest.jsonl').read_bytes()).hexdigest(),
        'protocol_sha256': hashlib.sha256(protocol_path.read_bytes()).hexdigest(),
        'confirmation_gold_opened': False
    })
    print('Frozen model comparison prepared; no API calls made.')


if __name__ == '__main__':
    main()
