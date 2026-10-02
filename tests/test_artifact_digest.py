"""Coverage hashes identify the immutable material dispatched for review."""

import hashlib
import json

import pytest

from agentjury import Artifact, Panel, ReviewRequest
from agentjury.judges.base import Completion, Judge


def digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_full_artifact_recomputes_supplied_digest():
    artifact = Artifact(name="answer.txt", content="323", content_sha256=digest("324"))
    assert artifact.content_sha256 == digest("323")


@pytest.mark.parametrize("mutation", ["content", "digest"])
def test_panel_coverage_identifies_actual_reviewed_content(mutation):
    artifact = Artifact(name="answer.txt", content="324")
    request = ReviewRequest(task="Write 323.", output="Done.", artifacts=[artifact])
    artifact.content = "323"
    if mutation == "digest":
        artifact.content_sha256 = digest("unrelated")

    class ContentJudge(Judge):
        provider = "test"

        def complete(self, system, user):
            material = json.loads(user.split("\n\n", 1)[1])
            assert material["deliverables"][1]["text"] == "323"
            # A caller edit during completion cannot change certified coverage.
            request.artifacts[0].content = "later edit"
            return Completion(text=json.dumps({
                "vote": "approve", "score": 9, "reason": "Correct file.", "findings": [],
            }))

    verdict = Panel([ContentJudge("accuracy", "offline")]).review(request)
    assert verdict.status == "verified"
    assert verdict.reviews[0].vote == "approve"
    assert verdict.artifact_coverage[0].content_sha256 == digest("323")


def test_partial_artifact_retains_full_source_digest_at_panel_boundary():
    source_hash = digest("complete source")
    artifact = Artifact(name="excerpt.txt", content="complete", coverage="partial",
                        content_sha256=source_hash)
    artifact.content = "source"
    from agentjury.judges import FakeJudge
    verdict = Panel([FakeJudge("accuracy")]).review(
        ReviewRequest(task="Review excerpt.", output="Done.", artifacts=[artifact]))
    assert verdict.artifact_coverage[0].coverage == "partial"
    assert verdict.artifact_coverage[0].content_sha256 == source_hash
