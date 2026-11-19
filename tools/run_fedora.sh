#!/usr/bin/env bash
set -euo pipefail

repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
exec "$repo/.venv/bin/python" "$repo/apps/pdf_to_mcq.py" "$@"
