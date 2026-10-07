# AgentJury release notes: unreleased changes

Unreleased on `main` after 0.5.1. Add new entries below this paragraph as
changes land; when a version is prepared, move them into
`docs/RELEASE_NOTES_v<version>.md`.

- The CLI now reads the `.env` file of the working directory or a parent
  (`find_dotenv(usecwd=True)`). An installed package previously searched from
  its own location, so a project's `.env` was read only from a checkout.

Released versions: [v0.5.1](RELEASE_NOTES_v0.5.1.md), [v0.5.0](RELEASE_NOTES_v0.5.0.md),
[v0.4.4](RELEASE_NOTES_v0.4.4.md), [v0.4.3](RELEASE_NOTES_v0.4.3.md).
