"""Run three real judges on one piece of agent output and print their reviews."""

from dotenv import load_dotenv

from agentjury import ReviewRequest
from agentjury.judges import anthropic_judge, openai_judge

load_dotenv()  # reads OPENAI_API_KEY and ANTHROPIC_API_KEY from the .env file

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

judges = [
    openai_judge("accuracy"),
    anthropic_judge("critic"),
    openai_judge("executive"),
]

for judge in judges:
    print(f"Asking {judge.name} ({judge.model})...")
    review = judge.review(request)
    arrow = "▲" if review.vote == "approve" else "▼"
    print(f"  {arrow} {review.score:.0f}/10  {review.reason}")
    for issue in review.issues:
        print(f"     - {issue}")
    if review.blocking:
        print("     BLOCKING")
    print()
