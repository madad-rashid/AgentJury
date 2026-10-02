# Single OpenRouter diagnostic completion - 2026-10-02

Rashid explicitly authorized exactly one diagnostic paid completion at
20:03:14 UTC. The run used reviewed PR8 head
`e8775b95c9416e63de8faa34bd276d99223b6eff`, original synthetic case
`dev-original-injection`, exact model `openai/gpt-6.1-sol`, and the same first
messages as the earlier frozen test. The plan records message/source/runner
hashes. Independent review and three offline driver cases passed before dispatch.

## Actual result

Exactly **one inference call**, no retry, repair or further comparison.
The call started at 20:07:22 UTC; after 7.322 seconds its response was rejected at **completion validation** with
`unexpected_native_finish_reason`; the shared ledger halted with
`incomplete_completion`. Actual response metadata: HTTP 200, exact requested
model and OpenAI provider, one choice, no top-level or choice error,
`finish_reason=stop`, and a nonempty string message. The native finish field
contained **`completed`**, established by an additional static boolean captured
from that field before validation. The reviewed harness redacted this unknown
label as `unrecognized`; the supplementary diagnostic did not change acceptance.
The actual rejection is the native-finish allowlist mismatch, not an observed
truncation, model/provider mismatch, missing content or accounting failure.
The guard remains unchanged and rejected the response.

Prompt/completion usage: **1151 / 182 tokens**. Transport latency: **7.322s**.
No response content, reasoning, headers or raw identifiers were retained.
There is **no semantic grade, vote or evidence-validation result** for this call.
The new call does not establish the first historical call's rejection branch.

## Budget and accounting

Preflight verified the unchanged dedicated $3 non-resetting key cap, exact
prior accounted spend $0.004636, remaining allowance $2.995364 and existing
account credit sufficient for the new reservation. No account/credential change
or top-up occurred. The prior spend plus the conservative $0.057344 reservation
made the maximum aggregate obligation **$0.061980** before dispatch.

The response reports **$0.004696 incremental**, **$0.009332 cumulative** including
the prior reconciled call. These are response-reported amounts. Immediate
nonbillable reconciliation at 20:07:29 UTC still showed key usage $0.004636,
incremental key usage $0, and generation HTTP 404. **As of 20:07:29 UTC, the
second call's settled service accounting was unresolved; that snapshot did not
establish a free call or a confirmed settled charge.** Its conservative
**$0.057344** reservation remained held then. The later bounded read is recorded separately; historical
observations are never overwritten. No further inference is authorized here.

A single later nonbillable key read at **20:10:18 UTC** now records cumulative
usage **$0.009332**, incremental **$0.004696**, and remaining **$2.990668**,
with the cap unchanged. The dedicated key's service accounting therefore
reconciles the response-reported cost. Generation metadata remains unavailable
and was not retried; there is no independently reconciled generation cost for
this second call. The earlier unresolved observation and conservative
reservation remain historical records. No continuing polling or further spend
followed. Five nonbillable GETs were made by this diagnostic workflow: key and
credits preflight, key and generation immediately afterward, then one later key
read. The key-usage reconciliation is not an independent audit of payment data.

## Interpretation and next work

[OpenRouter documents](https://openrouter.ai/docs/api_reference/overview) that
`finish_reason` is normalized while `native_finish_reason` retains the raw
provider-specific label. [Its normalization announcement](https://openrouter.ai/blog/announcements/standardized-finish-reasons/)
describes that distinction. The observed `stop`/`completed` pair points to a
provider-label compatibility issue in the current native finish guard. This is
an inference about the intended mapping, not proof of semantic correctness or
permission to accept every unknown native label.

The next useful step is an **offline, separately scoped adapter compatibility
fix and review**: verify the OpenAI/OpenRouter meaning of `completed`, add a
synthetic regression for the exact observed metadata pair, and assess a narrow
provider-specific mapping while preserving normalized `stop`, exact model,
choice/error/content, token, privacy/routing and budget checks. Unknown/error,
length, max-token, refusal and disagreeing normalized-finish cases must remain
closed. Do not weaken the guard or spend more to continue the benchmark merely
because this response arrived. No such product change is made in this report.

## Reproducibility and checks

The isolated driver calls `complete()` once, never `review()`. An outer `Once`
guard plus a runtime tightening of ledger maximum calls to one reject further
dispatch; all other reviewed controls are unchanged. A new output directory
refuses rerun before credential or network use. The plan and conservative
reservation persist before paid HTTP. Prior spend is initialized in the ledger,
so its `reported_actual_usd` field is cumulative for this diagnostic run.

The same controls remain: direct OpenAI only, no fallback, required parameters,
data collection denied, prompt/completion price ceilings $2/$10 per million,
zero request fee, low reasoning effort, 4096 output tokens including reasoning,
8192 input-token reservation, 90-second timeout and zero retries. Offline driver
tests cover success/rejection with exactly one dispatch, no repair, rerun refusal,
preflight failure with zero dispatch and journal content redaction. The reviewed
harness's 54 focused tests passed again before the authorized call.

Independent result/privacy review, documentation/package checks and exact-head
CI results are recorded in the PR verification comment. Product source and the
reviewed harness are unchanged by this documentation-only follow-up. The raw
original review payload is already published in the earlier frozen investigation;
this report records its hash rather than duplicating request or response content.
The driver source below is historical evidence, not renewed permission to run it.

### plan.json

```json
{
  "head": "e8775b95c9416e63de8faa34bd276d99223b6eff",
  "case": "dev-original-injection",
  "model": "openai/gpt-6.1-sol",
  "message_sha256": "307f9ffb6d57dc5f65e20c96759727d234588f2a965c537331364a1e4acf84c3",
  "sources": {
    "experiments/openrouter/capped_transport.py": "973eb1c2c022c0e1665c37ea105c639cabb2065ecc6a895a2955b6eb85ae88f1",
    "agentjury/judges/openrouter.py": "578d2e04cc5de2b6afc34b3303e7fa34b0eb90554c5d79b15971ef8ff8bcd18f",
    "agentjury/judges/compatible.py": "6ee8b88a0da03159adbd09af1235757e25a4ca55a21e1cbef565b0c2d4568603",
    "agentjury/judges/base.py": "0e0beb9ebcd742a9eb6941dc7f8203ca226c0fa20602590f5366e8073e17cb43"
  },
  "runner_sha256": "35a52589a56316350e1cec827e8cfeede8b87cd10a9b83863c9e372a11af20a5",
  "maximum_inference_calls": 1,
  "repair_calls": 0,
  "retries": 0,
  "prior_settled_usd": "0.004636",
  "reserved_incremental_usd": "0.057344",
  "maximum_aggregate_obligation_usd": "0.061980",
  "total_cap_usd": "3",
  "authorization_utc": "2026-10-02T20:03:14+00:00"
}
```

### preflight.json

```json
{
  "observed_at_utc": "2026-10-02T20:07:21.488680+00:00",
  "inference_calls": 0,
  "ready": true,
  "key_limit_usd": "3",
  "key_remaining_usd": "2.995364",
  "prior_settled_usd": "0.004636",
  "nonresetting": true,
  "account_credit_covers_reservation": true
}
```

### journal.json

```json
{
  "calls": [
    {
      "attempt": 1,
      "case_id": {
        "present": true,
        "type": "string",
        "sha256": "6d00f85fbed92e3435736afae0837228237a57ce25af441b1f9d33121ff0646e"
      },
      "model": "openai/gpt-6.1-sol",
      "phase": "initial",
      "reserved_usd": "0.057344",
      "status": "stopped",
      "diagnostic": {
        "validation_stage": "completion",
        "error_category": "unexpected_native_finish_reason",
        "http_status": 200,
        "http_request_id": {
          "present": false,
          "type": "null",
          "sha256": null
        },
        "response_type": "object",
        "generation_id": {
          "present": true,
          "type": "string",
          "sha256": "8ae0cc1cecad4307a85052937b829326e06f95e91b7889b8e7c05d421b505f18"
        },
        "request_id": {
          "present": false,
          "type": "null",
          "sha256": null
        },
        "observed_model": "openai/gpt-6.1-sol",
        "observed_provider": "OpenAI",
        "top_level_error_present": false,
        "choices_type": "array",
        "choices_count": 1,
        "choice_error_present": false,
        "message_type": "object",
        "content_type": "string",
        "content_nonempty": true,
        "usage_type": "object",
        "finish_reason": "stop",
        "finish_reason_present": true,
        "finish_reason_type": "string",
        "native_finish_reason": "unrecognized",
        "native_finish_reason_present": true,
        "native_finish_reason_type": "string",
        "usage_field_types": {
          "cost": "number",
          "prompt_tokens": "number",
          "completion_tokens": "number"
        }
      },
      "seconds": 7.322,
      "reported_cost_usd": "0.004696",
      "prompt_tokens": 1151,
      "completion_tokens": 182
    }
  ],
  "reported_actual_usd": "0.009332",
  "reserved_attempts_usd": "0.057344",
  "halted": "incomplete_completion"
}
```

### result.json

```json
{
  "observed_at_utc": "2026-10-02T20:07:22.133761+00:00",
  "maximum_inference_calls": 1,
  "repair_or_retry_calls": 0,
  "completion_accepted": false,
  "semantic_grade": "unavailable",
  "actual_inference_calls": 1,
  "diagnostic": {
    "validation_stage": "completion",
    "error_category": "unexpected_native_finish_reason",
    "http_status": 200,
    "http_request_id": {
      "present": false,
      "type": "null",
      "sha256": null
    },
    "response_type": "object",
    "generation_id": {
      "present": true,
      "type": "string",
      "sha256": "8ae0cc1cecad4307a85052937b829326e06f95e91b7889b8e7c05d421b505f18"
    },
    "request_id": {
      "present": false,
      "type": "null",
      "sha256": null
    },
    "observed_model": "openai/gpt-6.1-sol",
    "observed_provider": "OpenAI",
    "top_level_error_present": false,
    "choices_type": "array",
    "choices_count": 1,
    "choice_error_present": false,
    "message_type": "object",
    "content_type": "string",
    "content_nonempty": true,
    "usage_type": "object",
    "finish_reason": "stop",
    "finish_reason_present": true,
    "finish_reason_type": "string",
    "native_finish_reason": "unrecognized",
    "native_finish_reason_present": true,
    "native_finish_reason_type": "string",
    "usage_field_types": {
      "cost": "number",
      "prompt_tokens": "number",
      "completion_tokens": "number"
    }
  },
  "supplemental_diagnostic": {
    "native_finish_is_completed": true
  },
  "incremental_response_reported_usd": "0.004696",
  "cumulative_response_reported_usd": "0.009332",
  "conservative_incremental_reservation_usd": "0.057344"
}
```

### accounting.json

```json
{
  "observed_at_utc": "2026-10-02T20:07:29.460159+00:00",
  "additional_inference_calls": 0,
  "settled_incremental_verified": false,
  "cumulative_key_usage_usd": "0.004636",
  "incremental_key_usage_usd": "0.000000",
  "key_remaining_usd": "2.995364",
  "key_cap_unchanged": true,
  "key_matches_reported": false,
  "generation_error_category": "http_failure",
  "generation_http_status": 404
}
```

### Frozen isolated driver

```python
"""Single explicitly authorized completion; never call review/repair/retry."""
import hashlib, importlib.util, io, json, os, subprocess, sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, build_opener

ROOT = Path(__file__).parent
REPO = ROOT/'AgentJury-fixes'
OUT = ROOT/'openrouter-one-diagnostic'
HEAD = 'e8775b95c9416e63de8faa34bd276d99223b6eff'
PRIOR = Decimal('0.004636')
MODEL = 'openai/gpt-6.1-sol'
sys.path.insert(0,str(REPO))
from agentjury.judges.openrouter import OpenRouterJudge, _NoRedirect
from agentjury.judges.compatible import _router_model_matches
from agentjury.judges.base import REPAIR_TEMPLATE
spec=importlib.util.spec_from_file_location('diagnostic',REPO/'experiments/openrouter/capped_transport.py')
h=importlib.util.module_from_spec(spec);spec.loader.exec_module(h)
opener=build_opener(_NoRedirect())

def get(path):
    assert path.startswith('/api/v1/')
    request=Request('https://openrouter.ai'+path,headers={'Authorization':'Bearer '+os.environ['OPENROUTER_API_KEY'],'Accept':'application/json'})
    with opener.open(request,timeout=30) as response:return json.load(response)['data']

def write(name,data):
    with (OUT/name).open('x',encoding='utf-8') as handle:json.dump(data,handle,indent=2)

class CapturedResponse(io.BytesIO):
    def __init__(self,raw,status,headers):
        super().__init__(raw);self.status=status;self.headers=headers

class Once:
    def __init__(self,inner):self.inner=inner;self.calls=0;self.generation_id=None;self.supplement={}
    def open(self,request,timeout):
        if self.calls:raise RuntimeError('one_completion_only')
        self.calls+=1
        with self.inner.open(request,timeout=timeout) as response:
            raw=response.read();status=getattr(response,'status',None);headers=getattr(response,'headers',None)
        try:
            data=json.loads(raw)
            if isinstance(data,dict):
                value=data.get('id')
                if isinstance(value,str) and value.startswith('gen-'):self.generation_id=value
                choices=data.get('choices');choice=choices[0] if isinstance(choices,list) and len(choices)==1 and isinstance(choices[0],dict) else {}
                native=choice.get('native_finish_reason')
                # This additional static label is diagnostic only, never an acceptance rule.
                self.supplement['native_finish_is_completed']=native=='completed'
        except (ValueError,UnicodeError):pass
        return CapturedResponse(raw,status,headers)

def execute():
    OUT.mkdir(exist_ok=False) # Refuse rerun before any credential/network use.
    assert subprocess.check_output(['git','-C',str(REPO),'rev-parse','HEAD'],text=True).strip()==HEAD
    old=json.loads((ROOT/'openrouter-capped-test/plan.json').read_text(encoding='utf-8'))
    case=next(c for c in old['cases'] if c['id']=='dev-original-injection')
    pre={'observed_at_utc':datetime.now(timezone.utc).isoformat(),'inference_calls':0,'ready':False}
    key=get('/api/v1/key')
    assert h.numeric(key['limit'])==3 and key.get('limit_reset') is None
    assert h.numeric(key['usage'])==PRIOR
    assert h.numeric(key['limit_remaining'])>=h.RESERVE and PRIOR+h.RESERVE<=3
    assert key.get('is_provisioning_key') is not True
    credits=get('/api/v1/credits')
    assert h.numeric(credits['total_credits'])-h.numeric(credits['total_usage'])>=h.RESERVE
    pre.update(ready=True,key_limit_usd='3',key_remaining_usd=str(h.numeric(key['limit_remaining'])),prior_settled_usd=str(PRIOR),nonresetting=True,account_credit_covers_reservation=True)
    write('preflight.json',pre)
    sources=['experiments/openrouter/capped_transport.py','agentjury/judges/openrouter.py','agentjury/judges/compatible.py','agentjury/judges/base.py']
    plan={'head':HEAD,'case':case['id'],'model':MODEL,'message_sha256':hashlib.sha256(json.dumps(case['messages'],sort_keys=True).encode()).hexdigest(),'sources':{p:hashlib.sha256((REPO/p).read_bytes()).hexdigest() for p in sources},'runner_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'maximum_inference_calls':1,'repair_calls':0,'retries':0,'prior_settled_usd':str(PRIOR),'reserved_incremental_usd':str(h.RESERVE),'maximum_aggregate_obligation_usd':str(PRIOR+h.RESERVE),'total_cap_usd':'3','authorization_utc':'2026-10-02T20:03:14+00:00'}
    write('plan.json',plan)
    h.MAX_CALLS=1 # Tighten the reviewed ledger; no other guard changes.
    ledger=h.Ledger(OUT/'journal.json');ledger.actual=PRIOR
    judge=OpenRouterJudge('accuracy',MODEL,timeout=90);judge.retries=0
    once=Once(judge._opener)
    judge._opener=h.CappedTransport(once,ledger,case['id'],MODEL,case['messages'],REPAIR_TEMPLATE,_router_model_matches)
    result={'observed_at_utc':datetime.now(timezone.utc).isoformat(),'maximum_inference_calls':1,'repair_or_retry_calls':0}
    try:
        completion=judge.complete(case['messages'][0]['content'],case['messages'][1]['content'])
        result['completion_accepted']=True
        result['semantic_grade']='not_evaluated_single_transport_diagnostic'
    except Exception:
        result['completion_accepted']=False
        result['semantic_grade']='unavailable'
    result.update(actual_inference_calls=once.calls,diagnostic=ledger.calls[0]['diagnostic'] if ledger.calls else None,supplemental_diagnostic=once.supplement,incremental_response_reported_usd=ledger.calls[0].get('reported_cost_usd') if ledger.calls else None,cumulative_response_reported_usd=str(ledger.actual),conservative_incremental_reservation_usd=str(h.RESERVE))
    write('result.json',result)
    print(json.dumps({'call_result':result}),flush=True) # Report before accounting cleanup.
    accounting={'observed_at_utc':datetime.now(timezone.utc).isoformat(),'additional_inference_calls':0,'settled_incremental_verified':False}
    try:
        final=get('/api/v1/key');usage=h.numeric(final['usage'])
        accounting.update(cumulative_key_usage_usd=str(usage),incremental_key_usage_usd=str(usage-PRIOR),key_remaining_usd=str(h.numeric(final['limit_remaining'])),key_cap_unchanged=h.numeric(final['limit'])==3 and final.get('limit_reset') is None,key_matches_reported=abs(usage-ledger.actual)<=Decimal('0.000001'))
    except Exception as exc:
        accounting['key_error_category']='http_failure' if isinstance(exc,HTTPError) else 'metadata_unavailable'
        if isinstance(exc,HTTPError):accounting['key_http_status']=exc.code
    if once.generation_id:
        try:
            generation=get('/api/v1/generation?'+urlencode({'id':once.generation_id}))
            cost=h.numeric(generation['total_cost']);accounting['generation_incremental_cost_usd']=str(cost)
            accounting['generation_matches_response']=result['incremental_response_reported_usd'] is not None and abs(cost-h.numeric(result['incremental_response_reported_usd']))<=Decimal('0.000001')
        except Exception as exc:
            accounting['generation_error_category']='http_failure' if isinstance(exc,HTTPError) else 'metadata_unavailable'
            if isinstance(exc,HTTPError):accounting['generation_http_status']=exc.code
    accounting['settled_incremental_verified']=bool(accounting.get('key_matches_reported') and accounting.get('generation_matches_response'))
    write('accounting.json',accounting);print(json.dumps({'accounting':accounting}),flush=True)

if __name__=='__main__':
    try:execute()
    except Exception as exc:
        safe={'stopped_before_or_outside_inference':True,'error_category':'http_failure' if isinstance(exc,HTTPError) else 'preflight_or_operator_validation_failure'}
        if isinstance(exc,HTTPError):safe['http_status']=exc.code
        print(json.dumps(safe),flush=True);sys.exit(2)

```

### Offline driver fixtures

```python
import importlib.util,io,json
from pathlib import Path
import pytest

ROOT=Path(__file__).parent
def runner():
    spec=importlib.util.spec_from_file_location('single_run',ROOT/'run-one-openrouter-diagnostic.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

@pytest.mark.parametrize('native',['stop','completed'])
def test_exactly_one_dispatch_and_no_repair(tmp_path,monkeypatch,native):
    r=runner();r.OUT=tmp_path/'fresh';monkeypatch.setenv('OPENROUTER_API_KEY','offline-dummy')
    count={'n':0}
    class Offline:
        def open(self,req,timeout):
            count['n']+=1;p=json.loads(req.data)
            assert timeout==90 and p['max_tokens']==4096
            assert p['provider']['allow_fallbacks'] is False
            return io.BytesIO(json.dumps({'id':'gen-offline','model':r.MODEL,'provider':'OpenAI','choices':[{'finish_reason':'stop','native_finish_reason':native,'message':{'content':'PRIVATE'}}],'usage':{'cost':0.0002,'prompt_tokens':100,'completion_tokens':10}}).encode())
    original=r.OpenRouterJudge
    class Judge(original):
        def __init__(self,*a,**kw):super().__init__(*a,**kw);self._opener=Offline()
    r.OpenRouterJudge=Judge
    def get(path):
        if path.startswith('/api/v1/generation'):return {'total_cost':0.0002}
        if path=='/api/v1/credits':return {'total_credits':3,'total_usage':0.004636}
        return {'limit':3,'limit_reset':None,'usage':0.004636+count['n']*0.0002,'limit_remaining':3-0.004636-count['n']*0.0002}
    r.get=get;r.execute()
    result=json.loads((r.OUT/'result.json').read_text())
    assert result['actual_inference_calls']==count['n']==1
    assert result['completion_accepted']==(native=='stop')
    assert result['repair_or_retry_calls']==0
    assert 'PRIVATE' not in (r.OUT/'journal.json').read_text()
    assert json.loads((r.OUT/'accounting.json').read_text())['settled_incremental_verified']
    with pytest.raises(FileExistsError):r.execute()
    assert count['n']==1

def test_preflight_failure_dispatches_nothing(tmp_path):
    r=runner();r.OUT=tmp_path/'fresh';r.get=lambda path:{'limit':30}
    with pytest.raises(AssertionError):r.execute()
    assert not (r.OUT/'journal.json').exists()

```


### Later key accounting observation

```json
{
  "observed_at_utc": "2026-10-02T20:10:18.963793+00:00",
  "additional_inference_calls": 0,
  "maximum_nonbillable_reads": 1,
  "dedicated_key_accounting_reconciled": true,
  "generation_metadata_not_retried": true,
  "cumulative_key_usage_usd": "0.009332",
  "incremental_key_usage_usd": "0.004696",
  "remaining_usd": "2.990668",
  "key_cap_unchanged": true
}
```
