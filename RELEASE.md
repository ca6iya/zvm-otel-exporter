# Release process

Maintainers cut releases. The current release is v0.2.0.

1. Confirm `main` is green on the CI workflow.
2. Update the version in `pyproject.toml` and `src/zvm_otel_exporter/__init__.py` so they match.
3. Move the `[Unreleased]` notes in [CHANGELOG.md](CHANGELOG.md) under a new `## [x.y.z] - YYYY-MM-DD` heading and add the compare link. Follow [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
4. Open a pull request. Merging it is the maintainer vote that the release is ready.
5. Tag the merge commit as `vx.y.z` and publish a GitHub Release whose body is the changelog section.
6. Do not publish a release that includes unfixed vulnerability reports still inside the response window in [SECURITY.md](SECURITY.md).
