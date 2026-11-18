# SPDX-License-Identifier: Apache-2.0
"""Allow ``python -m zvm_otel_exporter``."""

from zvm_otel_exporter.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
