"""Direct SDK adapters fail closed before untrusted telemetry reaches Review."""

import json
import types
import importlib
import sys

import pytest

from agentjury import Panel, ReviewRequest
from agentjury.judges.base import Judge
from agentjury.judges.openai_judge import OpenAIJudge
from agentjury.judges.anthropic_judge import AnthropicJudge

OPINION = json.dumps({'vote': 'approve', 'score': 9, 'reason': 'Fine.', 'findings': []})
REQUEST = ReviewRequest(task='Calculate 2+2.', output='4')


def stub(route, **changes):
    if route == 'openai':
        judge = OpenAIJudge.__new__(OpenAIJudge)
        response = types.SimpleNamespace(model='test-model', id='id', usage=None,
            choices=[types.SimpleNamespace(finish_reason='stop',
                message=types.SimpleNamespace(content=OPINION))])
        create_holder = types.SimpleNamespace()
        judge._client = types.SimpleNamespace(chat=types.SimpleNamespace(completions=create_holder))
    else:
        judge = AnthropicJudge.__new__(AnthropicJudge)
        response = types.SimpleNamespace(model='test-model', id='id', usage=None,
            stop_reason='end_turn', content=[types.SimpleNamespace(type='text', text=OPINION)])
        create_holder = types.SimpleNamespace()
        judge._client = types.SimpleNamespace(messages=create_holder)
        judge.max_tokens, judge.effort, judge.thinking = 1024, 'medium', 'adaptive'
    Judge.__init__(judge, 'accuracy', 'test-model', retries=0)
    for key, value in changes.items():
        setattr(response, key, value)
    create_holder.create = lambda **kwargs: response
    return judge, response, create_holder


@pytest.mark.parametrize('route', ['openai', 'anthropic'])
def test_direct_success_records_observed_model(route):
    judge, _, _ = stub(route)
    review = judge.review(REQUEST)
    assert review.observed_model == 'test-model'


@pytest.mark.parametrize('route', ['openai', 'anthropic'])
def test_direct_model_mismatch_is_unavailable(route):
    judge, _, _ = stub(route, model='PRIVATE_PROVIDER_BODY_MARKER')
    verdict = Panel([judge]).review(REQUEST)
    assert verdict.status == 'insufficient_jury'
    assert 'PRIVATE_PROVIDER_BODY_MARKER' not in verdict.model_dump_json()


@pytest.mark.parametrize('route', ['openai', 'anthropic'])
def test_direct_truncated_valid_json_is_unavailable(route):
    judge, response, _ = stub(route)
    if route == 'openai':
        response.choices[0].finish_reason = 'length'
    else:
        response.stop_reason = 'max_tokens'
    assert Panel([judge]).review(REQUEST).status == 'insufficient_jury'


@pytest.mark.parametrize('route', ['openai', 'anthropic'])
@pytest.mark.parametrize('field', ['id', 'usage'])
def test_direct_untrusted_telemetry_does_not_escape(route, field):
    judge, response, _ = stub(route)
    if field == 'id':
        response.id = {'secret': 'PRIVATE_PROVIDER_BODY_MARKER'}
    else:
        response.usage = types.SimpleNamespace(prompt_tokens='PRIVATE_PROVIDER_BODY_MARKER',
            input_tokens='PRIVATE_PROVIDER_BODY_MARKER')
    verdict = Panel([judge]).review(REQUEST)
    assert verdict.status == 'insufficient_jury'
    assert 'PRIVATE_PROVIDER_BODY_MARKER' not in verdict.model_dump_json()


@pytest.mark.parametrize('route', ['openai', 'anthropic'])
def test_direct_exception_does_not_echo_provider_body(route):
    judge, _, holder = stub(route)
    def fail(**kwargs):
        raise RuntimeError('PRIVATE_PROVIDER_BODY_MARKER')
    holder.create = fail
    verdict = Panel([judge]).review(REQUEST)
    assert verdict.status == 'insufficient_jury'
    assert 'PRIVATE_PROVIDER_BODY_MARKER' not in verdict.model_dump_json()


@pytest.mark.parametrize('route,date', [('openai', '2026-10-02'), ('anthropic', '20261002')])
def test_direct_alias_accepts_reported_dated_snapshot(route, date):
    judge, _, _ = stub(route, model=f'test-model-{date}')
    review = judge.review(REQUEST)
    assert review.model == 'test-model' and review.observed_model == f'test-model-{date}'


@pytest.mark.parametrize('route', ['openai', 'anthropic'])
def test_direct_sdk_disables_redirects_and_hidden_retries(route, monkeypatch):
    sdk = importlib.import_module(route)
    captured = {}
    class Client:
        def __init__(self, **kwargs):
            captured.update(kwargs)
    monkeypatch.delenv('ANTHROPIC_WORKSPACE_ID', raising=False)
    monkeypatch.setitem(sys.modules, route, types.SimpleNamespace(
        **{('OpenAI' if route == 'openai' else 'Anthropic'): Client},
        DefaultHttpxClient=sdk.DefaultHttpxClient))
    (OpenAIJudge if route == 'openai' else AnthropicJudge)('accuracy', 'test-model')
    assert captured['max_retries'] == 0
    assert captured['http_client'].follow_redirects is False
    captured['http_client'].close()
