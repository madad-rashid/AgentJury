import json
from collections import Counter

import pytest

from agentjury.benchmark_cases import BenchmarkCase, case_hash, case_request, load_cases


def _pack(tmp_path, cases, version="1"):
    path = tmp_path / "cases.json"
    path.write_text(json.dumps({"schema_version": version, "cases": cases}), encoding="utf-8")
    return path


def _case(**changes):
    return {"id": "c1", "task": "Calculate 2 + 2.", "output": "4", "label": "correct", **changes}


def test_starter_pack_has_varied_balanced_cases():
    cases, digest = load_cases(None)
    labels = Counter(case.label for case in cases)
    assert len(cases) >= 6
    assert all(labels[label] >= 2 for label in ("correct", "flawed", "injected"))
    assert any("alphabet" in case.task.lower() or "bullet" in case.task.lower() for case in cases)
    assert len(digest) == 64


@pytest.mark.parametrize("cases,version", [
    ([], "1"),
    ([_case(id="")], "1"),
    ([_case(task="   ")], "1"),
    ([_case(output="")], "1"),
    ([_case(label="other")], "1"),
    ([_case(), _case()], "1"),
    ([_case(extra="no")], "1"),
    ([_case(output=True)], "1"),
    ([_case()], "2"),
])
def test_invalid_cases_fail_with_safe_message(tmp_path, cases, version):
    with pytest.raises(ValueError, match="case file"):
        load_cases(_pack(tmp_path, cases, version))


def test_malformed_json_and_bom_fail(tmp_path):
    path = tmp_path / "cases.json"
    for raw in (b"{broken", b"\xef\xbb\xbf" + b'{"schema_version":"1","cases":[]}'):
        path.write_bytes(raw)
        with pytest.raises(ValueError, match="case file"):
            load_cases(path)


def test_content_hash_and_request(tmp_path):
    cases, digest = load_cases(_pack(tmp_path, [_case()]))
    assert len(digest) == 64
    changed = BenchmarkCase.model_validate(_case(output="5"))
    assert case_hash(cases[0]) != case_hash(changed)
    request = case_request(cases[0])
    assert request.task == cases[0].task
    assert request.output == cases[0].output
    assert request.request_id == case_hash(cases[0])[:12]
