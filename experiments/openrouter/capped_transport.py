"""Operator-only diagnostic transport for the capped synthetic experiment.

Importing does not make a request; no inference driver is included.
New inference requires separate authorization. Journals omit content,
headers, error text and raw identifiers. Original frozen evidence is unchanged."""
import io, json, time, hashlib
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.error import HTTPError
from agentjury.judges.response_validation import openrouter_finish_matches
MODELS = {'openai/gpt-6.1-sol': ('openai', 'OpenAI'), 'anthropic/claude-sonnet-5.5': ('anthropic', 'Anthropic')}
RESERVE = Decimal('0.057344')
CAP = Decimal('3')
MAX_CALLS = 32

class TestStopped(RuntimeError):
    pass

def numeric(value):
    if isinstance(value, bool) or value is None:
        raise TestStopped('missing_accounting')
    try:
        n = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise TestStopped('invalid_accounting') from None
    if not n.is_finite() or n < 0:
        raise TestStopped('invalid_accounting')
    return n

def shape(value):
    return 'null' if value is None else 'boolean' if isinstance(value, bool) else 'string' if isinstance(value, str) else 'object' if isinstance(value, dict) else 'array' if isinstance(value, list) else 'number' if isinstance(value, (int, float)) else 'other'

def fingerprint(value):
    return {'present': value is not None, 'type': shape(value), 'sha256': hashlib.sha256(value.encode('utf-8', errors='surrogatepass')).hexdigest() if isinstance(value, str) else None}

def label(value, allowed):
    return value if isinstance(value, str) and value in allowed else 'unrecognized' if value is not None else None

def response_diagnostic(data):
    d = {'response_type': shape(data)}
    if not isinstance(data, dict):
        return d
    choices = data.get('choices')
    choice = choices[0] if isinstance(choices, list) and len(choices) == 1 and isinstance(choices[0], dict) else {}
    message = choice.get('message')
    content = message.get('content') if isinstance(message, dict) else None
    usage = data.get('usage')
    finish = {'stop', 'length', 'tool_calls', 'function_call', 'content_filter', 'error'}
    native = finish | {'end_turn', 'STOP', 'max_tokens', 'MAX_TOKENS', 'refusal', 'completed'}
    d.update(generation_id=fingerprint(data.get('id')), request_id=fingerprint(data.get('request_id')), observed_model=label(data.get('model'), MODELS), observed_provider=label(data.get('provider'), {'OpenAI', 'Anthropic', 'Azure'}), top_level_error_present=bool(data.get('error')), choices_type=shape(choices), choices_count=len(choices) if isinstance(choices, list) else None, choice_error_present=bool(choice.get('error')), message_type=shape(message), content_type=shape(content), content_nonempty=isinstance(content, str) and bool(content.strip()), usage_type=shape(usage))
    for key, allowed in [('finish_reason', finish), ('native_finish_reason', native)]:
        d[key] = label(choice.get(key), allowed)
        d[key + '_present'] = key in choice
        d[key + '_type'] = shape(choice.get(key))
    if isinstance(usage, dict):
        d['usage_field_types'] = {key: shape(usage.get(key)) for key in ('cost', 'prompt_tokens', 'completion_tokens')}
    return d

class Ledger:

    def __init__(self, path):
        self.path = Path(path)
        self.calls = []
        self.actual = Decimal('0')
        self.halted = None
        if self.path.exists():
            raise TestStopped('existing_journal_do_not_resume')

    def save(self):
        self.path.write_text(json.dumps({'calls': self.calls, 'reported_actual_usd': str(self.actual), 'reserved_attempts_usd': str(RESERVE * len(self.calls)), 'halted': self.halted}, indent=2), encoding='utf-8')

    def stop(self, reason):
        self.halted = reason
        self.save()
        raise TestStopped(reason)

    def reserve(self, case, model, payload, phase):
        if self.halted:
            raise TestStopped('test_already_stopped')
        if len(self.calls) >= MAX_CALLS or RESERVE * (len(self.calls) + 1) > CAP or self.actual + RESERVE > CAP:
            self.stop('budget_ceiling')
        item = {'attempt': len(self.calls) + 1, 'case_id': fingerprint(case), 'model': label(model, MODELS), 'phase': phase, 'reserved_usd': str(RESERVE), 'status': 'reserved', 'diagnostic': {'validation_stage': 'reserved', 'error_category': None}}
        self.calls.append(item)
        self.save()
        return item

class CappedTransport:

    def __init__(self, inner, ledger, case, model, messages, repair_template, model_matches):
        self.inner = inner
        self.ledger = ledger
        self.case = case
        self.model = model
        self.messages = messages
        self.repair_template = repair_template
        self.model_matches = model_matches
        self.n = 0

    def open(self, req, timeout):
        if req.full_url != 'https://openrouter.ai/api/v1/chat/completions' or req.get_method() != 'POST' or timeout != 90:
            self.ledger.stop('unexpected_destination_or_timeout')
        payload = json.loads(req.data)
        expected = [dict(x) for x in self.messages]
        if self.n == 1:
            expected[1]['content'] += '\n\n' + self.repair_template
        if self.n > 1 or payload != {'model': self.model, 'messages': expected, 'stream': False}:
            self.ledger.stop('unexpected_model_or_prompt')
        if sum((len(x['content'].encode('utf-8')) for x in expected)) + 1024 > 8192:
            self.ledger.stop('input_reservation_exceeded')
        tag, provider = MODELS[self.model]
        payload.update(max_tokens=4096, reasoning={'effort': 'low'}, provider={'only': [tag], 'order': [tag], 'allow_fallbacks': False, 'require_parameters': True, 'data_collection': 'deny', 'max_price': {'prompt': 2, 'completion': 10, 'request': 0}})
        item = self.ledger.reserve(self.case, self.model, payload, 'initial' if self.n == 0 else 'syntax_repair')
        self.n += 1
        req.data = json.dumps(payload).encode('utf-8')
        start = time.perf_counter()
        d = item['diagnostic']

        def reject(category, halt=None):
            d['error_category'] = category
            self.ledger.stop(halt or category)
        try:
            d['validation_stage'] = 'transport'
            with self.inner.open(req, timeout=90) as response:
                status = getattr(response, 'status', None)
                d['http_status'] = status if isinstance(status, int) and (not isinstance(status, bool)) else None
                headers = getattr(response, 'headers', None)
                if headers is not None:
                    d['http_request_id'] = fingerprint(headers.get('x-request-id'))
                raw = response.read()
            d['validation_stage'] = 'response_decode'
            data = json.loads(raw)
            item['seconds'] = round(time.perf_counter() - start, 3)
            d.update(response_diagnostic(data))
            d['validation_stage'] = 'provider_response'
            if not isinstance(data, dict) or data.get('error'):
                error = data.get('error') if isinstance(data, dict) else None
                code = error.get('code') if isinstance(error, dict) else None
                reject('unsupported_controls' if code in ('unsupported_parameter', 'unsupported_parameters') else 'provider_error', 'provider_error')
            d['validation_stage'] = 'accounting'
            usage = data.get('usage')
            cost = numeric(usage.get('cost') if isinstance(usage, dict) else None)
            self.ledger.actual += cost
            item['reported_cost_usd'] = str(cost)
            pin = usage.get('prompt_tokens')
            pout = usage.get('completion_tokens')
            if any((isinstance(x, bool) or not isinstance(x, int) or x < 0 for x in (pin, pout))):
                reject('invalid_accounting')
            response_id = data.get('id')
            if response_id is not None and (not isinstance(response_id, str) or not response_id.strip()):
                reject('invalid_response_id')
            item.update(prompt_tokens=pin, completion_tokens=pout)
            if cost > RESERVE or self.ledger.actual > CAP:
                reject('cost_reservation_exceeded')
            if pin > 8192 or pout > 4096:
                reject('token_limit_exceeded')
            d['validation_stage'] = 'provider'
            if data.get('provider') != provider:
                reject('provider_mismatch')
            d['validation_stage'] = 'model'
            if not self.model_matches(self.model, data.get('model')):
                reject('model_mismatch')
            d['validation_stage'] = 'completion'
            choices = data.get('choices')
            choice = choices[0] if isinstance(choices, list) and len(choices) == 1 and isinstance(choices[0], dict) else None
            if not choice:
                reject('missing_choice', 'incomplete_completion')
            if choice.get('error'):
                reject('choice_error', 'incomplete_completion')
            if choice.get('finish_reason') != 'stop':
                reject('truncated_completion' if choice.get('finish_reason') == 'length' else 'unexpected_finish_reason', 'incomplete_completion')
            if not openrouter_finish_matches(self.model, data.get('provider'), choice.get('finish_reason'), choice.get('native_finish_reason', 'stop')):
                reject('truncated_completion' if choice.get('native_finish_reason') in ('length', 'max_tokens', 'MAX_TOKENS') else 'unexpected_native_finish_reason', 'incomplete_completion')
            message = choice.get('message')
            content = message.get('content') if isinstance(message, dict) else None
            if not isinstance(content, str) or not content.strip():
                reject('missing_content', 'incomplete_completion')
            item['status'] = 'completed'
            d['validation_stage'] = 'accepted'
            self.ledger.save()
            return io.BytesIO(raw)
        except Exception as exc:
            item.setdefault('seconds', round(time.perf_counter() - start, 3))
            item['status'] = 'stopped'
            if isinstance(exc, HTTPError):
                d.update(http_status=exc.code, error_category='http_failure')
            elif isinstance(exc, TestStopped):
                if d['error_category'] is None:
                    d['error_category'] = 'missing_accounting' if str(exc) == 'missing_accounting' else 'invalid_accounting'
            elif isinstance(exc, (json.JSONDecodeError, UnicodeError)):
                d['error_category'] = 'malformed_response'
            else:
                d['error_category'] = 'transport_or_persistence_failure'
            if not self.ledger.halted:
                self.ledger.halted = 'transport_or_accounting_failure'
            self.ledger.save()
            raise TestStopped(self.ledger.halted) from None
