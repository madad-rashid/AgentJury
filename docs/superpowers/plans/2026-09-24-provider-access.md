# Provider Access Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let AgentJury review through OpenRouter, Ollama, or one configurable OpenAI-compatible endpoint using explicit models, while preserving its existing jury decisions.

**Architecture:** A shared Chat Completions judge handles the three new routes. A single panel factory parses model-bearing entries for both the CLI and Hermes. Existing `Judge` and `Panel` behavior remains authoritative for retries, independent votes, and aggregation.

**Tech Stack:** Python 3.11+, Pydantic 2, optional `openai` SDK, pytest, Git.

**Spec:** `docs/superpowers/specs/2026-09-24-provider-access-design.md`

## Global Constraints

- Python support remains `>=3.11`.
- `role:openai` and `role:anthropic` retain their current default models and behavior.
- New routes require explicit models; panel parsing splits at only the first two colons.
- OpenRouter requires `OPENROUTER_API_KEY`; Ollama defaults to `http://127.0.0.1:11434/v1`; custom uses `AGENTJURY_COMPATIBLE_BASE_URL` and optional `AGENTJURY_COMPATIBLE_API_KEY`.
- Endpoint URLs must be absolute HTTP(S) URLs without embedded credentials, query strings, or fragments.
- OpenRouter model slugs need a stable `vendor/model` prefix; dynamic aliases are rejected.
- Saved verdicts contain no API keys or raw endpoint URLs. They retain exact model, route, and a hashed endpoint identity.
- Quorum, provider floor, blocking, vote weights, schema fields, and schema version do not change.
- The default panel does not change; no live service or paid API is needed by the normal test suite.

## Review Focus

1. Local model names containing `:` must survive panel parsing. Test in Task 2.
2. Missing key, malformed URL, and unavailable endpoint must produce safe, actionable errors. Test in Task 1.
3. Two OpenRouter models from one vendor must remain one provider for the provider floor. Test in Task 3.
4. A direct OpenAI judge and an OpenRouter OpenAI model must remain one provider. Test in Task 3.
5. Duplicate judge display names or out-of-order completions must not reorder reviews. Test in Task 3.

---

### Task 1: Shared Compatible Judge

**Files:**
- Create: `agentjury/judges/compatible.py`
- Modify: `agentjury/judges/__init__.py`
- Test: `tests/test_compatible_judge.py`

**Interfaces:**
- Produces: `openrouter_judge(role: str, model: str) -> Judge`, `ollama_judge(role: str, model: str) -> Judge`, `compatible_judge(role: str, model: str) -> Judge`.
- Produces: a `Judge` whose `provider` is the OpenRouter model vendor, `ollama`, or `compatible`; whose `model` is the exact requested model; and whose `params` include `route` and `endpoint_hash`.
- Consumes: `Judge`, `Completion`, and environment settings from the approved spec.

- [ ] **Step 1: Prepare an isolated Python environment for this task.** Use the bundled Python at `C:\Users\qtr_r\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe` to create `.venv`, then run `& .\.venv\Scripts\python.exe -m pip install -e '.[all,dev]'`. `.venv` is ignored by the repository. If package downloads are blocked by the sandbox, request network escalation for this exact install rather than changing the global Python runtime.

- [ ] **Step 2: Write failing adapter tests.** In `tests/test_compatible_judge.py`, inject a fake `openai.OpenAI` into `sys.modules` before constructing a judge. Start the file with `import json, sys, types, pytest`, `from agentjury import Panel, ReviewRequest`, and this fixture, which captures constructor and request arguments and can simulate failures:

```python
@pytest.fixture
def fake_openai(monkeypatch):
    state = types.SimpleNamespace(kwargs=None, calls=[], error=None, texts=[])
    def create(**kwargs):
        state.calls.append(kwargs)
        if state.error:
            raise state.error
        opinion = {"vote": "approve", "score": 9, "reason": "Correct.", "findings": []}
        text = state.texts.pop(0) if state.texts else json.dumps(opinion)
        message = types.SimpleNamespace(content=text)
        choice = types.SimpleNamespace(message=message)
        usage = types.SimpleNamespace(prompt_tokens=11, completion_tokens=7)
        return types.SimpleNamespace(choices=[choice], usage=usage, id="resp-1")
    class Client:
        def __init__(self, **kwargs):
            state.kwargs = kwargs
            self.chat = types.SimpleNamespace(completions=types.SimpleNamespace(create=create))
    module = types.ModuleType("openai")
    module.OpenAI = Client
    monkeypatch.setitem(sys.modules, "openai", module)
    return state
```

Cover these concrete assertions:

```python
def test_openrouter_uses_one_key_and_vendor_identity(monkeypatch, fake_openai):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-router-key")
    from agentjury.judges import openrouter_judge
    judge = openrouter_judge("accuracy", "anthropic/claude-sonnet-4")
    review = judge.review(ReviewRequest(task="Check this", output="Answer"))
    assert judge.provider == "anthropic"
    assert review.model == "anthropic/claude-sonnet-4"
    assert review.params["route"] == "openrouter"
    assert fake_openai.kwargs["base_url"] == "https://openrouter.ai/api/v1"
    assert fake_openai.kwargs["api_key"] == "test-router-key"
    assert fake_openai.kwargs["max_retries"] == 0
    assert fake_openai.calls[0]["model"] == "anthropic/claude-sonnet-4"
    assert [m["role"] for m in fake_openai.calls[0]["messages"]] == ["system", "user"]
    assert "test-router-key" not in review.model_dump_json()
    assert review.tokens_in == 11 and review.tokens_out == 7
    assert review.response_id == "resp-1"

def test_ollama_uses_local_endpoint_without_user_key(monkeypatch, fake_openai):
    from agentjury.judges import ollama_judge
    review = ollama_judge("critic", "qwen3:8b").review(
        ReviewRequest(task="Check this", output="Answer"))
    assert review.provider == "ollama"
    assert review.model == "qwen3:8b"
    assert fake_openai.kwargs["base_url"] == "http://127.0.0.1:11434/v1"
    assert "endpoint_hash" in review.params
    assert "127.0.0.1" not in review.model_dump_json()
```

Parameterize URL validation over `ftp://host/v1`, `http://user:pass@host/v1`, `http://host/v1?token=x`, and `http://host/v1#fragment`; each must raise `ValueError`. Add missing-key and missing-custom-URL cases; each must name its required environment variable. Reject `~openai/gpt-latest`. Set `fake_openai.error = RuntimeError('SECRET_MARKER')`, call `judge.complete('system', 'user')`, and assert `SECRET_MARKER` is absent from the raised error. Set it to `ConnectionError('offline')`, run a one-judge `Panel`, and assert the verdict is `insufficient_jury` with a route/model error and no key or raw URL. Set `fake_openai.texts = ['not JSON', json.dumps({'vote': 'approve', 'score': 9, 'reason': 'Correct.', 'findings': []})]`, then assert `judge.review(request)` makes two calls and succeeds. Set `fake_openai.texts = ['not JSON', 'still not JSON']`, then assert a one-judge panel records a judge error and returns `insufficient_jury`.

- [ ] **Step 3: Run the new test file to confirm it fails for the missing constructors.** Run `& .\.venv\Scripts\python.exe -m pytest tests/test_compatible_judge.py -q`; expect an import or attribute failure before implementation.

- [ ] **Step 4: Implement the adapter and constructors.** Put URL validation in `compatible.py` using `urllib.parse.urlsplit`: require `scheme in {'http', 'https'}`, `netloc`, and no username, password, query, or fragment; normalize by removing one or more trailing slashes. Hash the normalized URL with `sha256(...).hexdigest()[:12]` for `params['endpoint_hash']`. Validate OpenRouter slugs with `re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*/[^\s/][^\s]*', model)`. Set `self.provider` before calling `Judge.review`, and override `name` to return `f'{self.role}/{self.route}/{self.model}'`. Construct `OpenAI(api_key=key or 'agentjury-no-key', base_url=url, timeout=timeout, max_retries=0)`. `complete` sends system and user messages to `chat.completions.create`, extracts text, usage, and response ID into `Completion`, and wraps SDK failures with route/model/error class/HTTP status only. Add the three public constructors to `judges/__init__.py`; import the SDK lazily so users of direct Anthropic do not need `openai` installed.

- [ ] **Step 5: Run the focused tests, then verify the saved review has no raw URL or key.** Run `& .\.venv\Scripts\python.exe -m pytest tests/test_compatible_judge.py -q`; inspect any failure and fix the adapter. Commit this task with `git add agentjury/judges/compatible.py agentjury/judges/__init__.py tests/test_compatible_judge.py` and `git commit -m 'feat: add compatible judge routes'` after it passes.

### Task 2: One Panel Parser for CLI and Hermes

**Files:**
- Create: `agentjury/panel_config.py`
- Modify: `agentjury/cli.py`
- Modify: `integrations/hermes/jury.py`
- Test: `tests/test_panel_config.py`
- Test: `tests/test_hermes_plugin.py`

**Interfaces:**
- Consumes: Task 1's five judge constructors (`openai_judge`, `anthropic_judge`, `openrouter_judge`, `ollama_judge`, `compatible_judge`).
- Produces: `build_panel(spec: str, quorum: int | None = None) -> Panel` in `agentjury.panel_config`; CLI's existing `build_panel` delegates to it, and Hermes passes `settings.panel` and `settings.quorum or None` to it.

- [ ] **Step 1: Write failing parser tests.** In `tests/test_panel_config.py`, import `pytest`, `FakeJudge`, and `build_panel` from `agentjury.panel_config`. Monkeypatch the factory functions on `agentjury.panel_config` to return `FakeJudge` instances and record the requested model. Assert old entries still build, new entries preserve models containing colons, a missing new-route model fails, and empty/unknown entries fail with useful text:

```python
def test_model_colon_is_preserved(monkeypatch):
    from agentjury import panel_config
    seen = []
    def local(role, model):
        seen.append((role, model))
        return FakeJudge(role, provider="ollama")
    monkeypatch.setattr(panel_config, "ollama_judge", local)
    panel_config.build_panel("accuracy:ollama:qwen3:8b")
    assert seen == [("accuracy", "qwen3:8b")]

@pytest.mark.parametrize("spec", ["accuracy:ollama", "accuracy:openrouter:",
                                   "accuracy:unknown:x", "accuracy", ","])
def test_invalid_panel_has_clear_error(spec):
    with pytest.raises(ValueError, match="panel|provider|model"):
        build_panel(spec)
```

Also assert `accuracy:openai` and `critic:anthropic` pass `model=None`, and `accuracy:openai:gpt-example` passes `model='gpt-example'`. In `tests/test_hermes_plugin.py`, add a case that monkeypatches `agentjury.panel_config.build_panel`, calls Hermes `build_panel(Settings(panel='accuracy:ollama:qwen3:8b'))`, and asserts the exact spec and quorum arguments were forwarded. Add a CLI case that checks its `build_panel` delegates to the same function and converts `ValueError` to a concise `SystemExit` message.

- [ ] **Step 2: Run the parser tests to observe the missing module and old parser failure.** Run `& .\.venv\Scripts\python.exe -m pytest tests/test_panel_config.py tests/test_hermes_plugin.py -q`; expect the newly added cases to fail.

- [ ] **Step 3: Implement the shared factory.** Split comma-separated items, reject empty entries, and use `item.split(':', 2)` for fields. Validate `role in ROLES` and `provider` in the five supported names. For direct providers call their constructor with the optional model; for new routes require a nonempty model and pass it through. Build `Panel(judges, quorum=quorum)`. CLI keeps its public `build_panel` name as a wrapper and displays parser `ValueError` using `sys.exit(str(exc))`; Hermes loads custom roles first, then calls the shared factory. Remove Hermes's duplicated provider registry.

- [ ] **Step 4: Run focused tests and the existing CLI/Hermes tests.** Run `& .\.venv\Scripts\python.exe -m pytest tests/test_panel_config.py tests/test_hermes_plugin.py tests/test_cli_adjudicate.py -q`. Commit with `git add agentjury/panel_config.py agentjury/cli.py integrations/hermes/jury.py tests/test_panel_config.py tests/test_hermes_plugin.py` and `git commit -m 'feat: share model-aware panel configuration'` after the tests pass.

### Task 3: Stable Ordering and Diversity Semantics

**Files:**
- Modify: `agentjury/panel.py`
- Modify: `agentjury/protocol.py`
- Test: `tests/test_aggregate.py`

**Interfaces:**
- Consumes: Task 1's declared `Judge.provider` and `Judge.name` values.
- Produces: `Panel.review` with results ordered by input index, including duplicate names. `Review.provider` documentation describes the known underlying model provider, with local/custom routes treated as one provider each.

- [ ] **Step 1: Add failing behavior tests.** In `tests/test_aggregate.py`, make two `FakeJudge('accuracy', provider='ollama')` instances with `delay=0.05` and `delay=0`, wrap each instance's `review` method to save its returned `review_id`, run `Panel([slow, fast]).review(REQ)`, and assert `verdict.reviews[0].review_id == slow.saved_id` and `verdict.reviews[1].review_id == fast.saved_id`. Add panels with provider labels `['openai', 'openai']` (single-provider panel can verify), `['openai', 'openai', 'anthropic']` where the Anthropic judge fails (status `insufficient_jury` despite two votes), and `['openai', 'anthropic']` (two-provider verdict allowed). One `openai` label represents a direct judge and the other an OpenRouter-routed OpenAI model; the test pins the model-provider rule.

```python
def test_requested_two_provider_panel_cannot_verify_from_one_vendor():
    judges = [FakeJudge("accuracy", provider="openai"),
              FakeJudge("critic", provider="openai"),
              FakeJudge("executive", provider="anthropic", fail_times=2)]
    verdict = Panel(judges).review(REQ)
    assert verdict.up == 2
    assert verdict.status == "insufficient_jury"
```

- [ ] **Step 2: Run `tests/test_aggregate.py` and confirm the new ordering case fails.** Use `& .\.venv\Scripts\python.exe -m pytest tests/test_aggregate.py -q`.

- [ ] **Step 3: Replace name-based sorting with index-based sorting.** Store each submitted future with `(index, judge)`, append `(index, review)` on completion, sort those pairs by index, and pass only the reviews to `aggregate`. Keep errors attached to the same judge name. Clarify the `Review.provider` field description and the module prose in `protocol.py`; do not add or rename schema fields.

- [ ] **Step 4: Run focused tests.** Run `& .\.venv\Scripts\python.exe -m pytest tests/test_aggregate.py tests/test_compatible_judge.py -q`. Commit with `git add agentjury/panel.py agentjury/protocol.py tests/test_aggregate.py` and `git commit -m 'fix: preserve panel order and provider identity'` after the tests pass.

### Task 4: Quick Starts and Full Offline Verification

**Files:**
- Modify: `README.md`
- Modify: `.env.example`
- Modify: `CONTRIBUTING.md`
- Modify: `integrations/hermes/README.md`

**Interfaces:**
- Consumes: Task 2's `role:provider:model` syntax and Task 1's four endpoint/key settings.
- Produces: copyable CLI and Hermes examples, no new runtime API.

- [ ] **Step 1: Update user instructions.** In `README.md`, add one-key OpenRouter and local Ollama commands using concrete model slugs and explain that users may substitute supported or installed models. Show `OPENROUTER_API_KEY`, `AGENTJURY_OLLAMA_BASE_URL`, `AGENTJURY_COMPATIBLE_BASE_URL`, and `AGENTJURY_COMPATIBLE_API_KEY` in `.env.example` without real secrets. Add a custom endpoint example with `accuracy:compatible:local-model`. Update Hermes installation and `panel` configuration examples, and explain that OpenRouter/custom endpoints receive reviewed task content. State that local/custom routes count as one provider and that OpenRouter diversity uses the model vendor slug. Update `CONTRIBUTING.md` with the shared adapter and panel parser extension points.

```powershell
$env:OPENROUTER_API_KEY = 'your-key'
agentjury review task.md output.md --panel 'accuracy:openrouter:openai/gpt-4o,critic:openrouter:anthropic/claude-sonnet-4'
agentjury review task.md output.md --panel 'accuracy:ollama:qwen3:8b,critic:ollama:qwen3:8b'
```

- [ ] **Step 2: Run the complete offline test suite and build.** Use `& .\.venv\Scripts\python.exe -m pytest tests -q` and `& .\.venv\Scripts\python.exe -m build`. Check `git diff --check`, inspect the generated wheel metadata and packaged `agentjury` modules, and confirm `git status --short` contains only intended docs and ignored local build artifacts. If the documented model slugs are no longer available, replace them with current examples from official provider docs before finalizing.

- [ ] **Step 3: Commit documentation and report validation limits.** Run `git add README.md .env.example CONTRIBUTING.md integrations/hermes/README.md` and `git commit -m 'docs: explain one-key and local jury setup'` after Step 2 passes. Report the full test count and build result. State clearly whether an optional live OpenRouter or Ollama call was run; do not claim live validation without it.

## Final Review

- [ ] Re-read the approved spec and compare every section against the implemented changes.
- [ ] Inspect the full branch diff for accidental key or URL disclosure, schema changes, CLI/Hermes drift, and changes to aggregation rules.
- [ ] Run `& .\.venv\Scripts\python.exe -m pytest tests -q`, `& .\.venv\Scripts\python.exe -m build`, and `git diff --check` fresh before claiming the phase is implemented.
- [ ] Use the finishing-development-branch workflow to choose how the reviewed work reaches the remote repository; publishing or merging needs the appropriate final approval if it was not already given.
