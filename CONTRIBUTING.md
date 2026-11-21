# Contributing

This exporter is licensed under the Apache License 2.0. See [LICENSE](LICENSE).
By submitting a contribution you agree that it can be distributed under that license.

Participants follow the [Code of Conduct](CODE_OF_CONDUCT.md). Roles, voting, and write access are in [GOVERNANCE.md](GOVERNANCE.md).

## Developer Certificate of Origin

Every commit must include a `Signed-off-by` trailer. This is required, not optional. The trailer certifies the [Developer Certificate of Origin](https://developercertificate.org/) version 1.1.

```bash
git commit -s
```

The trailer must match the commit author, for example:

```text
Signed-off-by: Your Name <you@example.com>
```

Pull requests whose commits lack the trailer fail the DCO workflow. Do not use a trailer for someone else.

## Development

Python 3.11 or newer is required. A z/VM system is not required.

```bash
python -m pip install -e ".[dev]"
ruff check .
ruff format --check .
pytest
```

The mock Feilong server uses the fixture in
`src/zvm_otel_exporter/fixtures/mock_feilong.json`:

```bash
zvm-otel-exporter-mock --port 8080
zvm-otel-exporter \
  --feilong-url http://127.0.0.1:8080 \
  --feilong-admin-token test-admin-token \
  --no-verify-tls \
  --once
```

`test-admin-token` is a fixture value. Do not reuse it for a real Feilong.

Recorded `vmcp` output used by the parser lives in
`src/zvm_otel_exporter/fixtures/vmcp/`.

## Security

Report vulnerabilities privately. The process is in [SECURITY.md](SECURITY.md). Do not file a public issue for a suspected vulnerability.

## Secrets

Do not put tokens in issues, commits, logs, or test fixtures that pretend to
be production credentials. The exporter redacts configured secrets, but a
reviewer should still check that new log statements print paths and status
codes rather than headers or response bodies. Do not call `GET /guests/{userid}`:
Feilong returns the user directory entry, and that entry contains the guest
password in clear text.

## Metrics

New instruments belong in `zvm_otel_exporter/catalog.py` and must be produced
by `translate.py` or `vmcp.py` from a documented source. Add the OpenTelemetry
name to the metrics table in `README.md`. Prefer a gap note over a metric whose
unit or meaning is not actually available. Do not add CP commands to the vmcp
collector without updating the performance limits in the README.

## Pull requests

GitHub Actions runs Ruff and pytest on Python 3.11 and 3.12, checks alert
rules with promtool, and checks `Signed-off-by` on each commit. Please keep
those workflows green. How to run the alert tests locally is in
[Testing the alert rules](docs/dashboards.md#testing-the-alert-rules). Describe
how you tested the change. Live z/VM results are welcome and should name the
z/VM and Feilong versions you used.

## Code review

[CodeRabbit](https://coderabbit.ai/) reviews every non-draft pull request to
`main`. The settings are in [`.coderabbit.yaml`](.coderabbit.yaml). Generated
Grafana and Dynatrace dashboard JSON is excluded, because
`dashboards/build_pack.py` writes those files. Comment on the generator and
the alert rules.

A maintainer still approves the change. CodeRabbit does not grant that
approval. Roles are in [GOVERNANCE.md](GOVERNANCE.md).

Do not merge while the latest commit has no CodeRabbit review, or while an
actionable CodeRabbit comment on that commit is still open. A rate-limited
review does not count as a review. The review on the pull request is the one
that counts. Ask for it there.

The `CodeRabbit` check stays pending while a review is running, and it fails
when a review errors. A rate-limited review still reports success, which is
why the rule above is a maintainer check and not only a status check. Require
that check in branch protection so an in-progress review cannot merge.
