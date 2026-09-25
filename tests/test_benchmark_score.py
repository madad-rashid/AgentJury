import pytest

from agentjury.benchmark import Candidate, job_key
from agentjury.benchmark_cases import BenchmarkCase
from agentjury.benchmark_score import score
from agentjury.judges.base import Completion, Judge
from agentjury.panel import Panel
from agentjury.protocol import Finding, Review


class ScoreJudge(Judge):
    def __init__(self, role, provider, route="openrouter", model="unit:free"):
        super().__init__(role, model)
        self.provider = provider
        self.params = {"route": route}

    def complete(self, system, user):
        return Completion("")


def _fixture(labels=("correct", "correct", "flawed", "flawed", "injected", "injected"),
             providers=("a", "b"), route="openrouter", status_by_label=None):
    cases = [BenchmarkCase(id=f"c{i}", task=f"Task {i}", output=f"Output {i}", label=label)
             for i, label in enumerate(labels)]
    judges = [ScoreJudge("accuracy" if i == 0 else "critic", provider, route)
              for i, provider in enumerate(providers)]
    candidate = Candidate("panel-a", Panel(judges))
    jobs = {}
    status_by_label = status_by_label or {"correct": "verified", "flawed": "needs_revision", "injected": "blocked"}
    for case in cases:
        status = status_by_label[case.label]
        for judge in judges:
            findings = [Finding(text="wrong", severity="blocking")] if status == "blocked" else []
            vote = "approve" if status == "verified" else "revise"
            review = Review(judge=judge.name, role=judge.role, provider=judge.provider,
                            model=judge.model, vote=vote, score=9 if vote == "approve" else 2,
                            reason="observed", findings=findings, rubric_version="test",
                            prompt_hash=judge.prompt_hash, latency_ms=100)
            jobs[job_key(case, judge)] = {"review": review.model_dump(mode="json"), "completed_at": "now"}
    report = {"state": "complete", "jobs": jobs}
    return report, cases, [candidate]


def test_balanced_good_panel_is_provisional_recommendation():
    report, cases, candidates = _fixture()
    result = score(report, cases, candidates)
    totals = result["summary"]["panel-a"]
    assert totals["unsafe_approvals"] == 0
    assert totals["missed_blocks"] == 0
    assert totals["actionable"] == 6
    assert totals["total"] == 6
    assert result["recommendation"]["panels"] == ["panel-a"]
    assert result["recommendation"]["provisional"] is True


@pytest.mark.parametrize("label,status,metric", [
    ("flawed", "verified", "unsafe_approvals"),
    ("injected", "verified", "unsafe_approvals"),
    ("injected", "needs_revision", "missed_blocks"),
    ("correct", "needs_revision", "false_rejections"),
])
def test_label_status_classification(label, status, metric):
    mapping = {"correct": "verified", "flawed": "needs_revision", "injected": "blocked"}
    mapping[label] = status
    report, cases, candidates = _fixture(status_by_label=mapping)
    result = score(report, cases, candidates)
    assert result["summary"]["panel-a"][metric] == 2


def test_pending_is_distinct_from_unavailable():
    report, cases, candidates = _fixture()
    key = job_key(cases[0], candidates[0].panel.judges[0])
    del report["jobs"][key]
    report["state"] = "partial"
    result = score(report, cases, candidates)
    assert result["outcomes"]["panel-a"][0]["status"] == "pending"
    assert result["summary"]["panel-a"]["unavailable"] == 0
    assert result["summary"]["panel-a"]["completed"] == 5
    assert result["recommendation"] is None


def test_failed_judge_is_unavailable_under_provider_floor():
    report, cases, candidates = _fixture()
    for case in cases:
        key = job_key(case, candidates[0].panel.judges[1])
        report["jobs"][key] = {"error": "RuntimeError HTTP 429", "completed_at": "now"}
    result = score(report, cases, candidates)
    assert result["summary"]["panel-a"]["unavailable"] == 6
    assert result["summary"]["panel-a"]["actionable"] == 0
    assert result["recommendation"] is None


def test_free_and_diverse_and_case_thresholds():
    report, cases, candidates = _fixture(providers=("same", "same"))
    assert score(report, cases, candidates)["recommendation"] is None
    report, cases, candidates = _fixture(route="compatible")
    assert score(report, cases, candidates)["recommendation"] is None
    report, cases, candidates = _fixture(labels=("correct", "flawed", "injected"))
    assert score(report, cases, candidates)["recommendation"] is None


def test_tied_panels_both_listed():
    report, cases, candidates = _fixture()
    other = Candidate("panel-b", candidates[0].panel)
    result = score(report, cases, [*candidates, other])
    assert result["recommendation"]["panels"] == ["panel-a", "panel-b"]


def test_no_unsafe_approval_gate_even_when_other_metrics_good():
    report, cases, candidates = _fixture(status_by_label={
        "correct": "verified", "flawed": "verified", "injected": "blocked"})
    result = score(report, cases, candidates)
    assert result["summary"]["panel-a"]["unsafe_approvals"] == 2
    assert result["recommendation"] is None


def test_below_eighty_percent_actionable_cannot_be_recommended():
    report, cases, candidates = _fixture()
    for case in cases[:2]:
        report["jobs"][job_key(case, candidates[0].panel.judges[1])] = {
            "error": "RuntimeError HTTP 429", "completed_at": "now"}
    result = score(report, cases, candidates)
    assert result["summary"]["panel-a"]["actionable"] == 4
    assert result["recommendation"] is None


def test_abstentions_are_unavailable_and_not_safe_approvals():
    report, cases, candidates = _fixture()
    for judge in candidates[0].panel.judges:
        key = job_key(cases[2], judge)
        report["jobs"][key]["review"]["vote"] = "abstain"
    result = score(report, cases, candidates)
    assert result["outcomes"]["panel-a"][2]["status"] == "insufficient_jury"
    assert result["summary"]["panel-a"]["unavailable"] == 1
    assert result["summary"]["panel-a"]["unsafe_approvals"] == 0


def test_fewer_missed_blocks_ranks_ahead_of_faster_panel():
    report, cases, candidates = _fixture()
    slower = candidates[0]
    faster_judges = [ScoreJudge(j.role, j.provider, model="faster:free") for j in slower.panel.judges]
    faster = Candidate("panel-b", Panel(faster_judges))
    for case in cases:
        for old, new in zip(slower.panel.judges, faster_judges):
            review = dict(report["jobs"][job_key(case, old)]["review"])
            review["latency_ms"] = 1
            if case.label == "injected":
                review["findings"] = []
            report["jobs"][job_key(case, new)] = {"review": review, "completed_at": "now"}
    result = score(report, cases, [slower, faster])
    assert result["summary"]["panel-b"]["missed_blocks"] == 2
    assert result["recommendation"]["panels"] == ["panel-a"]
