from dotenv import load_dotenv
load_dotenv()

from agentjury import ReviewRequest
from agentjury.judges import anthropic_judge
from agentjury.judges.base import build_user_prompt

j = anthropic_judge("critic")
req = ReviewRequest(task=open("examples/task.md").read(), output=open("examples/output.md").read())
r = j._client.messages.create(model=j.model, max_tokens=1024, system=j.system_prompt,
                              messages=[{"role": "user", "content": build_user_prompt(req)}])
print("stop_reason:", r.stop_reason)
print("blocks:", [b.type for b in r.content])
print("text:", repr("".join(b.text for b in r.content if b.type == "text"))[:500])