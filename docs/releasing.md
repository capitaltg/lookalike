# Releasing

Pushing a version tag runs the tests, builds the package, publishes it to
PyPI and creates a GitHub release. It is the same arrangement as
`capitaltg/icebergdx`: PyPI Trusted Publishing, so no token or password is
stored anywhere.

## Cut a release

1. Set the new version in `pyproject.toml` (`version = "0.2.0"`), run
   `uv lock`, and merge that to `main`.
2. Tag that commit on `main` and push the tag. The tag must be `v` plus the
   version:

   ```
   git checkout main && git pull
   git tag v0.2.0
   git push origin v0.2.0
   ```

3. Watch the `release` workflow under the repository's *Actions* tab. When it
   finishes, the version is on <https://pypi.org/project/lookalike/> and on
   the repository's *Releases* page.

A version can be published only once. PyPI never accepts the same file name
twice, even after deletion, so a mistake is fixed by releasing the next
version, not by re-pushing the tag. Release tags cannot be moved or deleted.

## What the workflow does

| Job | Does | Stops the release if |
|---|---|---|
| `verify` | Runs the full CI: tests on Python 3.10, 3.12 and 3.13, build, smoke test | Any test fails |
| `build` | Checks the tag, builds the wheel and sdist once, installs the wheel in a clean environment and runs it, records SHA-256 checksums | The tag does not equal `v` + the `pyproject.toml` version, the commit is not on `main`, or the smoke test fails |
| `pypi` | Uploads those exact files to PyPI with signed attestations | PyPI rejects the upload |
| `publish` | Creates the GitHub release with the same files and generated notes | |

## One-time setup

The GitHub side is already configured:

- environments `pypi` and `release`, each usable only from `v*` tags;
- tag rules: only repository admins can create `v*` tags, and nobody can
  move or delete them;
- repository variable `PYPI_PUBLISH=true`. Set it to anything else to make a
  release skip PyPI and only create the GitHub release.

The PyPI side has to be done once by a person, in the PyPI web interface. In
the `capitaltg` organization at <https://pypi.org/manage/organizations/>, open
*Publishing* and add a GitHub pending publisher:

| Field | Value |
|---|---|
| PyPI project name | `lookalike` |
| Owner | `capitaltg` |
| Repository name | `lookalike` |
| Workflow name | `release.yml` |
| Environment name | `pypi` |

The first successful release creates the project under the organization. A
pending publisher does not reserve the name, so cut the first release soon
after adding it. Until it is added, the `pypi` job fails and no GitHub release
is created.

## Good to know

- Publishing to PyPI makes the source code public, whatever the visibility of
  this repository.
- To try the build without releasing, run `uv build` and
  `scripts/smoke-test.sh dist/*.whl`.
