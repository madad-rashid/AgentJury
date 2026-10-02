import importlib.util, json, io
from urllib.request import Request
from decimal import Decimal
from pathlib import Path
import pytest
s = importlib.util.spec_from_file_location('support', Path(__file__).parents[1] / 'experiments/openrouter/capped_transport.py')
m = importlib.util.module_from_spec(s)
s.loader.exec_module(m)
MSG = [{'role': 'system', 'content': 'fixed system'}, {'role': 'user', 'content': 'fixed synthetic input'}]

class Offline:

    def __init__(self, response):
        self.response = response
        self.calls = 0
        self.sent = None

    def open(self, req, timeout):
        self.calls += 1
        self.sent = json.loads(req.data)
        return io.BytesIO(json.dumps(self.response).encode())

def response(**changes):
    d = {'id': 'synthetic', 'model': 'openai/gpt-6.1-sol', 'provider': 'OpenAI', 'choices': [{'finish_reason': 'stop', 'native_finish_reason': 'stop', 'message': {'content': '{"vote":"approve"}'}}], 'usage': {'cost': 0.0002, 'prompt_tokens': 100, 'completion_tokens': 10}}
    d.update(changes)
    return d

def setup(tmp_path, r):
    l = m.Ledger(tmp_path / 'journal.json')
    o = Offline(r)
    t = m.CappedTransport(o, l, 'case', 'openai/gpt-6.1-sol', MSG, 'repair', lambda a, b: a == b)
    return (l, o, t)

def req(messages=MSG):
    return Request('https://openrouter.ai/api/v1/chat/completions', data=json.dumps({'model': 'openai/gpt-6.1-sol', 'messages': messages, 'stream': False}).encode(), method='POST')

def test_fixed_controls_and_accounting(tmp_path):
    l, o, t = setup(tmp_path, response())
    t.open(req(), 90)
    assert o.sent['max_tokens'] == 4096 and o.sent['reasoning'] == {'effort': 'low'}
    assert o.sent['provider'] == {'only': ['openai'], 'order': ['openai'], 'allow_fallbacks': False, 'require_parameters': True, 'data_collection': 'deny', 'max_price': {'prompt': 2, 'completion': 10, 'request': 0}}
    assert o.sent['messages'] == MSG and l.actual == Decimal('0.0002') and (l.calls[0]['status'] == 'completed')

@pytest.mark.parametrize('delta', [{'provider': 'Azure'}, {'model': 'different/model'}, {'usage': {'prompt_tokens': 100, 'completion_tokens': 10}}, {'usage': {'cost': 0.1, 'prompt_tokens': 100, 'completion_tokens': 10}}, {'usage': {'cost': 0.001, 'prompt_tokens': 100, 'completion_tokens': 4097}}, {'choices': [{'finish_reason': 'length', 'message': {'content': 'partial'}}]}])
def test_failure_halts_without_retry(tmp_path, delta):
    l, o, t = setup(tmp_path, response(**delta))
    with pytest.raises(m.TestStopped):
        t.open(req(), 90)
    assert l.halted and o.calls == 1
    with pytest.raises(m.TestStopped):
        t.open(req(), 90)
    assert o.calls == 1

def test_prompt_change_stops_before_network(tmp_path):
    l, o, t = setup(tmp_path, response())
    with pytest.raises(m.TestStopped):
        t.open(req([{'role': 'system', 'content': 'changed'}, {'role': 'user', 'content': 'fixed synthetic input'}]), 90)
    assert o.calls == 0 and (not l.calls)

def test_thirty_third_attempt_is_never_sent(tmp_path):
    l, o, t = setup(tmp_path, response())
    l.calls = [{'status': 'completed'}] * 32
    with pytest.raises(m.TestStopped):
        l.reserve('case', 'openai/gpt-6.1-sol', {}, 'initial')
    assert len(l.calls) == 32 and o.calls == 0

def test_journal_cannot_accidentally_resume(tmp_path):
    p = tmp_path / 'journal.json'
    p.write_text('{}')
    with pytest.raises(m.TestStopped):
        m.Ledger(p)

@pytest.mark.parametrize('usage', [{'cost': 0.0002, 'prompt_tokens': '100', 'completion_tokens': 10}, {'cost': 0.0002, 'prompt_tokens': True, 'completion_tokens': 10}])
def test_noninteger_token_metadata_halts_and_preserves_known_cost(tmp_path, usage):
    l, o, t = setup(tmp_path, response(usage=usage))
    with pytest.raises(m.TestStopped):
        t.open(req(), 90)
    assert l.actual == Decimal('0.0002') and l.halted and (o.calls == 1)

def test_invalid_response_id_halts(tmp_path):
    l, o, t = setup(tmp_path, response(id=123))
    with pytest.raises(m.TestStopped):
        t.open(req(), 90)
    assert l.halted and o.calls == 1
