# Publishing AgentJury

This checklist keeps package identity, Git tags, GitHub Releases, and PyPI aligned.

## Current release note

Package metadata is prepared as `0.5.0`; the published release remains `0.4.4`.
This preparation does not authorize publishing. After the release-readiness PR
is merged, separately authorize publication, confirm `0.5.0` is still unused on
GitHub and PyPI, and rebuild fresh artifacts from the exact approved commit.
Never reuse older validation artifacts or move an existing release tag.

The normal publication route is `.github/workflows/publish.yml`: publishing a
GitHub Release triggers a tag/version check, source/wheel build, and PyPI trusted
publication using the `pypi` environment and OIDC. Before publishing, a maintainer
must confirm the PyPI trusted publisher matches this repository, workflow and
environment, and that any environment approvals are configured as intended.
Those service-side settings have not been verified by this preparation.

## One-time PyPI setup

1. Create or sign in to a PyPI account at <https://pypi.org/>.
2. Enable two-factor authentication.
3. Confirm the existing GitHub workflow's PyPI trusted publisher registration and `pypi` environment. Use a project token only for a separately approved manual fallback.
4. Never commit a PyPI token to this repository.

## Release checklist

From a clean checkout of `main` after the release PR is merged:

```bash
python -m venv .venv
```

Activate the environment, then install development dependencies:

```bash
pip install -e ".[all,dev]"
```

Run tests:

```bash
python -m pytest tests -q
```

Confirm both version locations match:

```bash
python -c "import agentjury; print(agentjury.__version__)"
```

Check `pyproject.toml` has the same version.

Build the distributions:

```bash
python -m build
```

Validate package metadata:

```bash
python -m twine check dist/*
```

Optional TestPyPI check, only with separate publication approval:

```bash
python -m twine upload --repository testpypi dist/*
```

Install the TestPyPI build in a fresh environment and run a basic CLI check.

Proceed with the normal GitHub Release route below. A manual PyPI upload is a
separately approved alternative, not a step in this sequence; never upload the
same version manually and through the release-triggered workflow.

## GitHub tag and Release

Only after tests and package validation succeed:

```bash
git tag -a v0.5.0 -m "AgentJury v0.5.0 public alpha"
git push origin v0.5.0
```

Create a GitHub Release from the new tag using finalized notes derived from
`docs/RELEASE_NOTES_UNRELEASED.md`.

Do not retag an existing version. If a release mistake is found after publication, increment the patch version.

## After PyPI publication

Update README installation instructions from the GitHub direct install to:

```bash
pip install "agentjury[all]"
```

Then verify:

```bash
pip install "agentjury[all]==0.5.0"
agentjury roles
```

- PyPI project page renders the README correctly
- source and wheel distributions are present
- `agentjury roles` works from a fresh environment
- GitHub Release points at the matching tag
- package metadata and `agentjury.__version__` match the tag

## Existing automation and publication transition

Use the existing GitHub Release-triggered trusted-publishing workflow as the
normal route. The build job verifies the tag equals `v0.5.0`; it does not replace
the full offline suite, package checks and exact-commit CI before release approval.

After successful PyPI publication, verify both artifacts and installation from
PyPI. In a follow-up, change the Hermes manifest's immutable guarded Git pin to
`agentjury>=0.5.0,<0.6` and align README/migration/Hermes installation guidance.
Before that confirmation, retain the source pin; do not claim an unavailable
PyPI version is installable. The pin's metadata version is historical 0.4.4,
but its source includes schema/policy 0.7 and the restored preset safeguard.
