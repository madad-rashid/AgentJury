"""Run a full panel: three judges in parallel, aggregated into one verdict."""

import time

from dotenv import load_dotenv

from agentjury import Panel, ReviewRequest
from agentjury.judges import anthropic_judge, openai_judge

load_dotenv()

request = ReviewRequest(
    task="In under 120 words, explain to an institutional investor why private credit "
         "has grown since 2010. Include one number with a source.",
    output=(
        "Private credit has grown from roughly $300 billion in 2010 to around $1.7 trillion "
        "today, according to Preqin. Post-2008 bank regulation, especially Basel III capital "
        "requirements, made it more expensive for banks to hold leveraged loans, so mid-market "
        "borrowers turned to non-bank lenders. At the same time, a decade of near-zero rates "
        "pushed pension funds and insurers toward higher-yielding private assets. Floating-rate "
        "structures also made the asset class attractive when rates began rising in 2022. "
        "The result is a market that now rivals high-yield bonds in size."
    ),
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
print(f"confidence {verdict.confidence:.0%}   ({elapsed:.0f}s, {len(verdict.reviews)} judges in parallel)")
print()
for r in verdict.reviews:
    arrow = "▲" if r.vote == "approve" else "▼"
    print(f"{arrow} {r.score:.0f}  {r.judge:<22} {r.reason}")
for e in verdict.errors:
    print(f"!  {e}")
