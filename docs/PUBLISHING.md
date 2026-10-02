# Publishing AgentJury

This checklist keeps package identity, Git tags, GitHub Releases, and PyPI aligned.

## Current release note

Package metadata currently reports `0.4.4`. The local integrity/provider changes
are unreleased and their validation builds retain that version. Before an
authorized release, choose an unused next version after checking existing Git
tags and PyPI releases, update both version locations, and rebuild. Never upload
the local validation artifacts under an already published version, and never
move or recreate an existing release tag. Replace `NEXT_VERSION` below with the
approved new version.

## One-time PyPI setup

1. Create or sign in to a PyPI account at <https://pypi.org/>.
2. Enable two-factor authentication.
3. Create a PyPI project token after the first trusted/manual publish, or configure GitHub Actions trusted publishing later.
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

Optional first publish to TestPyPI:

```bash
python -m twine upload --repository testpypi dist/*
```

Install the TestPyPI build in a fresh environment and run a basic CLI check.

Publish to PyPI:

```bash
python -m twine upload dist/*
```

Verify installation from PyPI in a fresh environment:

```bash
pip install "agentjury[all]==NEXT_VERSION"
agentjury roles
```

## GitHub tag and Release

Only after tests and package validation succeed:

```bash
git tag -a vNEXT_VERSION -m "AgentJury vNEXT_VERSION public alpha"
git push origin vNEXT_VERSION
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

- PyPI project page renders the README correctly
- source and wheel distributions are present
- `agentjury roles` works from a fresh environment
- GitHub Release points at the matching tag
- package metadata and `agentjury.__version__` match the tag

## Future automation

Once the first PyPI release is confirmed, prefer PyPI Trusted Publishing from GitHub Actions rather than storing a long-lived PyPI API token as a repository secret.
