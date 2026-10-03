# Claude Code change review implementation plan

The user approved the design in
[the specification](../specs/2026-10-03-claude-code-change-review-design.md)
with all recommended options. Work happens on the session's feature branch.
No merge, release, publication or paid model call is authorized.

## Constraints

Keep `protocol.py`, `aggregate.py`, `panel.py`, `panel_config.py`, the judges,
the rubric and Hermes unchanged. `agentjury review` keeps its behavior. New
commands reuse `Panel.review`, the reviewer guard, evidence checks and
adjudication. Offline tests must never contact a provider.

## Task 1: snapshot capture

Files: `agentjury/change_snapshot.py`, `tests/test_change_snapshot.py`.
Discover changes with Git plumbing (`diff --raw -z --no-renames`,
`ls-files --others --exclude-standard -z`), classify exclusions by name and
mode before reading content, build per-file diffs with fixed formatting flags
(untracked files are rendered locally), hash working-tree bytes, compute Git
blob IDs without writing, enforce caps and record offsets. Test each change
type, exclusion class, selection rule, path containment, symlinks, binary
content, caps and staleness comparison.

## Task 2: secret scanning

Files: `agentjury/change_secrets.py`, `tests/test_change_secrets.py`.
Detect private-key blocks, provider token formats, quoted credential
assignments and secret-named environment values. Report source, line and rule
only. Test detections, placeholders, allow IDs and absence of matched values.

## Task 3: bundle, send and status

Files: `agentjury/change_review.py`, `agentjury/data/change_roles.json`,
`agentjury/cli.py`, `tests/test_change_cli.py`.
Build the request and context, construct the panel through a seam, compute the
payload digest, write the bundle and preview, and print the manifest. Send
verifies and reviews once, then saves the verdict, coverage and binding. Status
compares bytes and renders numbered, escaped findings. Test refusals with zero
judge calls, success with listing and adjudication, invariants, display and
exit codes. Add `agentjury --version`.

## Task 4: Claude Code plugin

Files: `integrations/claude-code/**`, `.claude-plugin/marketplace.json`,
`MANIFEST.in`, `tests/test_claude_code_plugin.py`.
Add the three user-invoked skills, the send-deny hook and installation notes.
Statically test manifests, skill frontmatter, pre-approvals and the hook.

## Task 5: documentation and validation

Update the README, security, evaluation, migration, contributing and
unreleased release notes. Run `python -m pytest tests -q` offline,
`python -m build` and `twine check dist/*`, and check the sdist contents.
Review the diff adversarially before committing and pushing.
