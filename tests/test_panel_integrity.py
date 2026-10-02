import pytest

from agentjury import Panel
from agentjury.judges import FakeJudge
from test_compatible_judge import fake_openai


def test_same_configuration_cannot_cast_two_votes():
    with pytest.raises(ValueError, match="[Dd]uplicate"):
        Panel([FakeJudge("accuracy"), FakeJudge("accuracy")])


def test_different_roles_remain_distinct_reviewers():
    assert len(Panel([FakeJudge("accuracy"), FakeJudge("critic")]).judges) == 2


@pytest.mark.parametrize("route", ["native", "ollama", "compatible"])
def test_equivalent_ollama_aliases_cannot_cast_two_votes(monkeypatch, fake_openai, route):
    from agentjury.judges.ollama import OllamaJudge
    from agentjury.judges.compatible import compatible_judge, ollama_judge
    monkeypatch.setenv("AGENTJURY_OLLAMA_URL", "http://localhost:1234")
    monkeypatch.setenv("AGENTJURY_COMPATIBLE_BASE_URL", "http://localhost:1234/v1")
    factory = {"native": OllamaJudge, "ollama": ollama_judge, "compatible": compatible_judge}[route]
    first, second = factory("accuracy", "foo"), factory("accuracy", "foo:latest")
    assert [first.model, second.model] == ["foo", "foo:latest"]
    assert [first.params["requested_model"], second.params["requested_model"]] == ["foo", "foo:latest"]
    with pytest.raises(ValueError, match="[Dd]uplicate"):
        Panel([first, second])


def test_ollama_transport_and_explicit_tags_remain_distinct(monkeypatch, fake_openai):
    from agentjury.judges.ollama import OllamaJudge
    from agentjury.judges.compatible import ollama_judge
    monkeypatch.setenv("AGENTJURY_OLLAMA_URL", "http://localhost:1234")
    assert len(Panel([OllamaJudge("accuracy", "foo"), ollama_judge("accuracy", "foo:latest")]).judges) == 2
    assert len(Panel([OllamaJudge("accuracy", "foo:8b"), OllamaJudge("accuracy", "foo:latest")]).judges) == 2
