"""Smoke test: build one request, three reviews, and a verdict by hand."""

from agentjury import Agent, Review, ReviewRequest, Verdict, Vote

request = ReviewRequest(
    task="Summarise the private-credit pilot memo in under 200 words.",
    output="The pilot targets three institutional counterparties...",
    agent=Agent(name="hermes-research", framework="hermes", model="claude-fable-5-1"),
)

reviews = [
    Review(judge="accuracy", model="gpt-5.6-sol", vote=Vote.APPROVE, score=9,
           reason="Figures match the source memo."),
    Review(judge="critic", model="claude-fable-5-1", vote=Vote.REVISE, score=6,
           reason="Pricing assumption has no source.", issues=["Unsourced pricing"]),
    Review(judge="executive", model="gpt-5.6-sol", vote=Vote.APPROVE, score=8,
           reason="Concise and actionable."),
]

verdict = Verdict(
    request_id=request.request_id,
    up=2, down=1, score=7.67, consensus=0.67, confidence=0.7,
    status="verified", reviews=reviews,
)

print(verdict.render())
print()
print(verdict.model_dump_json(indent=2))
