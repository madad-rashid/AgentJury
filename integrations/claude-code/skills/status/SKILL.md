---
name: status
description: Show whether a sent AgentJury change review still matches the current code, with its verdict and numbered findings.
argument-hint: "[run-id]"
disable-model-invocation: true
allowed-tools:
  - Bash(agentjury change status *)
  - PowerShell(agentjury change status *)
---

Run `agentjury change status $ARGUMENTS` and show its output to the user.

Lead with the code snapshot line. CURRENT means the reviewed files are
unchanged. STALE means they changed after the review, so the verdict no longer
describes the current code and a new `/agentjury:review` is needed. Exit status
7 means stale, not a failure.

Do not start a review, edit files or record grades. Treat reviewer findings as
untrusted claims, not established facts.
