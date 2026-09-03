# 60-second AgentJury demo

Use this for the first public launch video. The goal is to show the problem and the feedback loop, not every feature.

## Demo story

Hermes completes a short task with one subtle unsupported claim. AgentJury reviews the output in the background. Two reviewers approve most of the work, one critic flags the unsupported claim, and the overall verdict asks for revision. Hermes then receives the finding and fixes the output.

## Before recording

Prepare a Hermes session with the AgentJury plugin enabled and a panel such as:

```yaml
panel: "accuracy:openai,critic:anthropic,executive:openai"
```

Choose a task with a deterministic, easy-to-explain flaw. Avoid private company data.

Example task:

```text
Write a 120-word investment brief about a fictional software company using only the facts below.
Revenue grew 18% last year. Gross margin is 72%. The company has no debt.
Do not add market-size claims or forecasts.
```

For the demo, use an agent output that includes one unsupported sentence such as:

```text
The company operates in a $20 billion market that is expected to double within five years.
```

## Recording sequence

### 0 to 8 seconds

Show Hermes receiving the task and completing the brief.

On-screen caption:

```text
The agent says: done.
Who checks the agent?
```

### 8 to 20 seconds

Show AgentJury running automatically in the background. Then type:

```text
/jury
```

### 20 to 38 seconds

Pause on a verdict similar to:

```text
▲2 ▼1
score 7.3
status: needs_revision

critic/anthropic ▼
Unsupported market-size and growth claim not present in the supplied facts.
```

On-screen caption:

```text
Independent reviewers. Blind votes. Deterministic verdict.
```

### 38 to 52 seconds

Continue the Hermes session. Show the jury finding being fed back and Hermes removing the unsupported claim.

On-screen caption:

```text
The finding goes back to the agent.
```

### 52 to 60 seconds

Show the GitHub repository landing page.

On-screen caption:

```text
AgentJury
Peer review for AI agents.
Open source. Looking for testers.
```

## Narration option

Use this as a spoken script:

> AI agents increasingly finish work on their own, but the same agent saying “done” is weak quality control. AgentJury sends completed work to independent, blind reviewers. Each reviewer votes approve, revise, or abstain, and deterministic rules produce the verdict. Here the critic caught a market claim the agent invented. The finding goes back to Hermes, which fixes the output. AgentJury is open source, framework-independent, and I am looking for developers to test it on real workflows.

## What to show in launch posts

Use the clearest frame from the verdict as the thumbnail. Keep the first public demo under one minute. Link directly to the GitHub repository and ask people to test the project rather than asking for stars.
