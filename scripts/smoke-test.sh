#!/usr/bin/env bash
# Install a built wheel into a clean environment (no project source on the path) and run the
# CLI end to end on the example file. Usage: scripts/smoke-test.sh dist/lookalike-X.Y.Z-py3-none-any.whl
set -euo pipefail

wheel=$(cd "$(dirname "$1")" && pwd)/$(basename "$1")
example=$(cd "$(dirname "$0")/.." && pwd)/examples/customers.csv
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

cd "$work"
uv venv --quiet --python 3.12 venv
uv pip install --quiet --python venv/bin/python "$wheel"
venv/bin/lookalike --help > /dev/null
venv/bin/lookalike anonymize "$example" out.csv --report report.json
venv/bin/lookalike verify "$example" out.csv
test "$(wc -l < out.csv)" -eq "$(wc -l < "$example")"
echo "smoke test passed: $(basename "$wheel")"
