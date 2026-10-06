# Publishing AgentJury

This checklist keeps package identity, Git tags, GitHub Releases, and PyPI aligned.

## Release history

### 0.5.0

Version 0.5.0 is published on [PyPI](https://pypi.org/project/agentjury/0.5.0/)
and [GitHub](https://github.com/madad-rashid/AgentJury/releases/tag/v0.5.0)
from commit `8aa02e1c5e9dc96149c1b99a5dc66e96d5a6770b`.
All eight post-merge CI jobs passed. The release-triggered
[publishing run](https://github.com/madad-rashid/AgentJury/actions/runs/37129743709)
succeeded through the existing `pypi` environment and OIDC workflow, with an
explicit approval for that deployment. Both artifact hashes, exact release
code, a clean PyPI installation, CLI and offline Hermes compatibility were checked.
This establishes successful publication; it does not imply ongoing service-side
settings audits or general model accuracy.

The normal route remains `.github/workflows/publish.yml`. Future releases require
their own approval, unused version/tag checks, exact-commit tests and fresh builds.
Do not reuse older validation artifacts, move an existing tag, or upload a
published version again. Repository installation/manifest updates do not replace the published
wheel, sdist or PyPI README snapshot; changing those requires a new patch release.

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

For a new, approved version only, after tests and package validation succeed
(replace `<new-version>`; `git tag -l` lists the tags that already exist):

```bash
git tag -a "v<new-version>" -m "AgentJury v<new-version> public alpha"
git push origin "v<new-version>"
```

Create a GitHub Release from the new tag using the finalized notes in
`docs/RELEASE_NOTES_v<new-version>.md`. Entries accumulate in
`docs/RELEASE_NOTES_UNRELEASED.md` between releases and move into that file
when the version is prepared.

Do not retag an existing version. If a release mistake is found after publication, increment the patch version.

## After PyPI publication

The Claude Code plugin and its marketplace are served from this repository, not
from the wheel. When a release first contains `agentjury change`, update the
plugin README's installation command to that release and increase the plugin
`version` if its files changed.

Keep README installation instructions aligned with the released compatibility
range. For the current 0.5 series:

```bash
python -m pip install "agentjury[all]>=0.5.1,<0.6"
```

Then verify the exact newly published version in a fresh environment
(replace `<new-version>`):

```bash
python -m pip install "agentjury[all]==<new-version>"
agentjury roles
```

- PyPI project page renders the README correctly
- source and wheel distributions are present
- `agentjury roles` works from a fresh environment
- GitHub Release points at the matching tag
- package metadata and `agentjury.__version__` match the tag
- the release history above gains the new version with its commit, tag and
  publishing run

## Existing automation and publication transition

Use the existing GitHub Release-triggered trusted-publishing workflow as the
normal route. The build job verifies the tag matches the package metadata
version; it does not replace the full offline suite, package checks and
exact-commit CI before release approval.

After every successful PyPI publication, verify both artifacts and a clean
installation from PyPI. Following confirmed 0.5.0 publication, the Hermes
manifest uses `agentjury>=0.5.0,<0.6`; README, migration and Hermes guidance
use the published package and explain targeted reinstallation and separate plugin
folder installation. Existing Hermes environments are not changed by this
repository transition. Historical Git pins and release artifacts remain intact.
