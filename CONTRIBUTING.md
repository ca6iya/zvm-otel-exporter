# Contributing

This exporter is licensed under the Apache License 2.0. By submitting a
contribution you agree that it can be distributed under that license.

The project is intended to be offered to the Open Mainframe Project. Please
follow the [Open Mainframe Project Code of Conduct](https://tac.openmainframeproject.org/code_of_conduct.html)
and add a `Signed-off-by` trailer when you want a commit to satisfy the
[Developer Certificate of Origin](https://developercertificate.org/).

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

## Secrets

Do not put tokens in issues, commits, logs, or test fixtures that pretend to
be production credentials. The exporter redacts configured secrets, but a
reviewer should still check that new log statements print paths and status
codes rather than headers or response bodies. Do not call `GET /guests/{userid}`:
Feilong returns the user directory entry, and that entry contains the guest
password in clear text.

## Metrics

New instruments belong in `zvm_otel_exporter/catalog.py` and must be produced
by `translate.py` from a documented Feilong field. Add the OpenTelemetry name
to the metrics table in `README.md`. Prefer a gap note over a metric whose
unit or meaning is not actually in the API.

## Pull requests

GitHub Actions runs Ruff and pytest on Python 3.11 and 3.12. Please keep that
workflow green. Describe how you tested the change. Live z/VM results are
welcome and should name the z/VM and Feilong versions you used.
