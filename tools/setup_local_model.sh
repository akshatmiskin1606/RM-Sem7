#!/usr/bin/env bash
set -euo pipefail

cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
runtime="$PWD/.kaqg-runtime"
ollama="$runtime/ollama/bin/ollama"
model="qwen3-vl:4b-instruct"
mkdir -p "$runtime/ollama"

if [[ ! -x "$ollama" ]]; then
    archive="$runtime/ollama-linux-amd64.tar.zst"
    curl --fail --location --retry 3 --connect-timeout 20 \
        https://ollama.com/download/ollama-linux-amd64.tar.zst --output "$archive"
    tar --zstd -xf "$archive" -C "$runtime/ollama"
    unlink "$archive"
fi

export OLLAMA_HOST=127.0.0.1:11439
export OLLAMA_MODELS="$runtime/models"
export OLLAMA_NO_CLOUD=1
"$ollama" serve > "$runtime/ollama-setup.log" 2>&1 &
server_pid=$!
cleanup() {
    kill "$server_pid" 2>/dev/null || true
    wait "$server_pid" 2>/dev/null || true
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

for attempt in {1..30}; do
    kill -0 "$server_pid" 2>/dev/null || break
    if curl --fail --silent --max-time 2 "http://$OLLAMA_HOST/api/version" >/dev/null; then
        "$ollama" pull "$model"
        exit 0
    fi
    sleep 1
done

cat "$runtime/ollama-setup.log" >&2
exit 1
