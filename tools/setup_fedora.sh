#!/usr/bin/env bash
set -euo pipefail

cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
runtime="$PWD/.kaqg-runtime"
mkdir -p "$runtime"

if [[ ! -x "$runtime/bootstrap/bin/uv" ]]; then
    python3 -m venv "$runtime/bootstrap"
    "$runtime/bootstrap/bin/python" -m pip --isolated install --no-cache-dir uv
fi

export UV_PYTHON_INSTALL_DIR="$runtime/python"
export UV_CACHE_DIR="$runtime/uv-cache"
uv="$runtime/bootstrap/bin/uv"
if [[ ! -x .venv/bin/python ]]; then
    "$uv" venv --python 3.12 --managed-python
fi
"$uv" pip install --python .venv/bin/python -r requirements.txt
"$uv" pip check --python .venv/bin/python

podman pull --policy=missing docker.io/library/neo4j:5.26.33-community
podman pull --policy=missing docker.io/library/eclipse-mosquitto:2.0
