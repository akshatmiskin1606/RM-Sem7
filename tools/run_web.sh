#!/usr/bin/env bash
set -euo pipefail

repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
npm --prefix "$repo/web" run build
exec "$repo/.venv/bin/python" "$repo/apps/serve_web.py" "$@"
