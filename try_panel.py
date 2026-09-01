"""Run a full panel: three judges in parallel, aggregated into one verdict."""

import time

from dotenv import load_dotenv

from agentjury import Panel, Producer, ReviewRequest
from agentjury.judges import anthropic_judge, openai_judge

load_dotenv()

request = ReviewRequest(
    task=open("examples/task.md", encoding="utf-8").read(),
    output=open("examples/output.md", encoding="utf-8").read(),
    task_type="summary",
    domain="private_credit",
    producer=Producer(agent="example", provider="anthropic", model="claude-fable-5-1"),
)

panel = Panel([
    openai_judge("accuracy"),
    anthropic_judge("critic"),
    openai_judge("executive"),
])

start = time.time()
verdict = panel.review(request)
elapsed = time.time() - start

print(verdict.render())
print(f"confidence {verdict.confidence:.0%}   ({elapsed:.0f}s wall clock)")
print()
for r in verdict.reviews:
    arrow = "▲" if r.vote == "approve" else "▼"
    print(f"{arrow} {r.score:.0f}  {r.judge:<22} {r.latency_ms}ms  {r.tokens_in}+{r.tokens_out} tok  {r.reason}")
    for f in r.findings:
        print(f"        [{f.severity}] {f.text}")
for e in verdict.errors:
    print(f"!  {e}")
