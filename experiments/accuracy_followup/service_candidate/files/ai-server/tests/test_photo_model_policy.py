"""Frozen single-photo model route; every model and lookup call is mocked."""
import asyncio
import hashlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from google.genai import types

from app import gemini_client
from app.config import get_settings
from app.schemas.model_response import ANALYZE_RESPONSE_SCHEMA
from app.services import vision


@pytest.fixture(autouse=True)
def baseline_settings(monkeypatch):
    for key, value in {'GEMINI_MODEL': 'gemini-2.5-flash', 'GEMINI_TEMPERATURE': '0',
                       'GEMINI_SEED': '20260722', 'GEMINI_THINKING_BUDGET': '0'}.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()


@pytest.fixture
def sdk_call(monkeypatch):
    call = AsyncMock(return_value=SimpleNamespace(text='{"candidates":[{"food_name":"밥"}]}'))
    monkeypatch.setattr(gemini_client, '_get_client', lambda: SimpleNamespace(
        aio=SimpleNamespace(models=SimpleNamespace(generate_content=call))))
    return call


@pytest.mark.parametrize('text', [None, '', ' \t\n'])
@pytest.mark.parametrize('url_field', ['image_url', 'image_urls'])
def test_frozen_route_config_and_actual_model_log(client, stub_download, sdk_call, text, url_field):
    stub_download()
    payload = {url_field: 'http://img/photo' if url_field == 'image_url' else ['http://img/photo'], 'user_text': text}
    body = client.post('/internal/analyze', json=payload).json()
    assert body['status'] == 'success'
    assert body['ai_call_log']['model_name'] == 'gemini-3.5-flash-lite'
    args = sdk_call.call_args.kwargs
    config = args['config']
    assert args['model'] == body['ai_call_log']['model_name']
    assert config.thinking_config.thinking_level == types.ThinkingLevel.MINIMAL
    assert config.thinking_config.thinking_budget is None
    assert config.max_output_tokens == 4096
    assert (config.temperature, config.seed) == (0, 20260722)
    assert config.response_json_schema == ANALYZE_RESPONSE_SCHEMA
    assert config.response_mime_type == 'application/json'
    assert config.tools is None
    assert len(args['contents']) == 2


@pytest.mark.parametrize('extra', [
    {'user_text': '밥도 먹었어'}, {'candidate_depth': 'clarifier'}, {'max_foods': 10},
    {'image_urls': ['http://img/first', 'http://img/second']},
])
def test_other_request_paths_keep_original_model_and_options(client, stub_download, sdk_call, extra):
    stub_download()
    body = client.post('/internal/analyze', json={'image_url': 'http://img/photo', **extra}).json()
    assert body['ai_call_log']['model_name'] == 'gemini-2.5-flash'
    args = sdk_call.call_args.kwargs
    assert args['model'] == 'gemini-2.5-flash'
    assert args['config'].thinking_config.thinking_budget == 0
    assert args['config'].thinking_config.thinking_level is None
    assert args['config'].max_output_tokens is None


@pytest.mark.parametrize('key,value', [('GEMINI_MODEL', 'operator-model'), ('GEMINI_TEMPERATURE', '.2'),
                                     ('GEMINI_SEED', '1'), ('GEMINI_THINKING_BUDGET', '512')])
def test_explicit_operator_settings_keep_existing_route(client, stub_download, sdk_call, monkeypatch, key, value):
    monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    stub_download()
    body = client.post('/internal/analyze', json={'image_url': 'http://img/photo'}).json()
    settings = get_settings()
    args = sdk_call.call_args.kwargs
    assert args['model'] == settings.gemini_model == body['ai_call_log']['model_name']
    assert args['config'].thinking_config.thinking_budget == settings.gemini_thinking_budget
    assert args['config'].thinking_config.thinking_level is None
    assert args['config'].max_output_tokens is None


@pytest.mark.parametrize('text,reason', [('bad', 'invalid_response'), ('{"candidates":[]}', 'not_food')])
def test_selected_model_logged_on_invalid_response(client, stub_download, sdk_call, text, reason):
    stub_download()
    sdk_call.return_value = SimpleNamespace(text=text)
    body = client.post('/internal/analyze', json={'image_url': 'http://img/photo'}).json()
    assert body['reason'] == reason
    assert body['ai_call_log']['model_name'] == 'gemini-3.5-flash-lite'
    assert body['failed_image_index'] is None


@pytest.mark.parametrize('error,reason', [(asyncio.TimeoutError(), 'ai_timeout'), (RuntimeError(), 'provider_error')])
def test_selected_provider_failures_keep_contract(client, stub_download, sdk_call, error, reason):
    stub_download()
    sdk_call.side_effect = error
    body = client.post('/internal/analyze', json={'image_url': 'http://img/photo'}).json()
    assert body['reason'] == reason
    assert body['failed_image_index'] is None
    assert body['fallback_action'] == 'manual_food_search'
    assert body['ai_call_log']['model_name'] == 'gemini-3.5-flash-lite'


def test_download_failure_keeps_index_and_never_calls_provider(client, stub_download, sdk_call):
    stub_download(exc=RuntimeError())
    body = client.post('/internal/analyze', json={'image_url': 'http://img/photo'}).json()
    assert (body['reason'], body['failed_image_index']) == ('provider_error', 0)
    sdk_call.assert_not_awaited()


def test_selected_route_still_attaches_package_labels_and_preserves_candidates(client, stub_download, sdk_call, monkeypatch):
    stub_download()
    sdk_call.return_value = SimpleNamespace(text=json.dumps({'candidates': [{
        'food_name': '참쌀설병', 'food_index': 0, 'image_index': 0, 'is_in_image': True,
        'estimated_serving_g': 9, 'count': 1, 'count_unit': '개', 'confidence': .9,
        'nutrition_per_100g': {'calories': 500, 'carbs': 70, 'protein': 5, 'fat': 20},
        'package': {'product_name': '참쌀설병', 'size_text': '9g', 'printed_kcal': 45},
    }]}))
    async def attach(candidates):
        candidates[0]['label'] = {'product_name': '확인된 이름', 'confidence': .9,
                                  'per_100g': {'calories': 500, 'carbs': 70, 'protein': 5, 'fat': 20}}
    lookup = AsyncMock(side_effect=attach)
    monkeypatch.setattr(vision.product_lookup, 'attach_labels', lookup)
    body = client.post('/internal/analyze', json={'image_url': 'http://img/photo'}).json()
    lookup.assert_awaited_once()
    candidate = body['candidates'][0]
    assert candidate['package']['printed_kcal'] == 45
    assert candidate['package']['size_g'] == 9
    assert (candidate['food_index'], candidate['image_index'], candidate['count'], candidate['count_unit']) == (0, 0, 1, '개')
    assert candidate['label']['product_name'] == '확인된 이름'


def test_prompt_and_schema_match_frozen_experiment():
    prompt = vision._build_prompt('standard', 5)
    assert hashlib.sha256(prompt.encode()).hexdigest() == 'ec03e8be7d47b2d48734f60354360246c78ea55c06d227de31907a7f8c71a7c7'
    semantic = json.dumps(ANALYZE_RESPONSE_SCHEMA, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
    assert hashlib.sha256(semantic).hexdigest() == '4e36ed481d5493f10d5e2ebc442559c542c1e1522142fdd7391f9ec53e25cf5d'


def test_generate_json_defaults_preserve_existing_sdk_config(sdk_call):
    asyncio.run(gemini_client.generate_json('other-caller', ['prompt']))
    config = sdk_call.call_args.kwargs['config']
    assert config.max_output_tokens is None
    assert config.thinking_config.thinking_budget == 0
    assert config.thinking_config.thinking_level is None
