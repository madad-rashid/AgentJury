"""The judge output parser has to survive real model behaviour."""

import pytest

from agentjury.judges import parse_opinion


def test_clean_json():
    o = parse_opinion('{"vote": "approve", "score": 9, "reason": "ok"}')
    assert o.vote == "approve" and o.score == 9 and o.findings == []


def test_code_fenced_json_with_chatter():
    raw = 'Sure, here is my review:\n```json\n{"vote": "revise", "score": 5, "reason": "weak", ' \
          '"findings": [{"text": "no source", "severity": "major"}]}\n```\nHope this helps!'
    o = parse_opinion(raw)
    assert o.vote == "revise"
    assert o.findings[0].severity == "major"


def test_missing_severity_defaults_to_minor():
    o = parse_opinion('{"vote": "approve", "score": 8, "reason": "ok", "findings": [{"text": "typo"}]}')
    assert o.findings[0].severity == "minor"


def test_rejects_bad_severity():
    with pytest.raises(ValueError):
        parse_opinion('{"vote": "approve", "score": 8, "reason": "ok", "findings": [{"text": "x", "severity": "huge"}]}')


def test_rejects_no_json():
    with pytest.raises(ValueError):
        parse_opinion("I think it is fine.")
