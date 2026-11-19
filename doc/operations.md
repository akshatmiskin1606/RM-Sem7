# Local operations and testing

Run the commands below from the KAQG repository root. The local setup targets Fedora x86-64 with rootless Podman, Bash, and Node.js/npm. The two optional log viewer windows use Konsole.

## Set up and launch

```bash
bash tools/setup_fedora.sh
bash tools/setup_local_model.sh
npm ci --prefix web
bash tools/run_web.sh --background
python3 tools/open_log_terminals.py
```

[`setup_fedora.sh`](../tools/setup_fedora.sh) bootstraps `uv`, creates a managed Python 3.12 `.venv`, installs [`requirements.txt`](../requirements.txt), and pulls the Neo4j 5.26.33 Community and Eclipse Mosquitto 2.0 images. [`setup_local_model.sh`](../tools/setup_local_model.sh) installs Ollama and pulls `qwen3-vl:4b-instruct` into `.kaqg-runtime/models/`. Setup uses the network to download dependencies. The configured local workspace can run inference offline after setup.

[`run_web.sh`](../tools/run_web.sh) builds the frontend and starts the Python server. Open [the local workspace](http://127.0.0.1:8765/). Use the launcher without `--background` for a foreground server. To use a different loopback port, set `--port` on the web launcher and pass the same value to the log viewer launcher.

## Two live log windows

[`open_log_terminals.py`](../tools/open_log_terminals.py) opens two separate Konsole windows, or reuses matching windows. Both follow the log files between jobs.

| Window | File | Contents |
| --- | --- | --- |
| **KAQG Backend** | `.kaqg-runtime/web-8765.log` | HTTP requests, worker stdout and stderr, job status changes, and Podman, Neo4j, and Mosquitto output during graph builds |
| **Qwen Model** | `.kaqg-runtime/ollama.log` | Ollama service and runner output, model loading, and inference requests |

The backend log file is written by the background launcher. In foreground mode the server and worker log output goes to the serving terminal. Model logs append to the same runtime file in both modes. The browser's **Activity** panel uses selected milestones from the backend stream. The model window receives new entries when a job starts the local model. Close either Konsole window to stop viewing that stream.

## Run from the command line

Build the graph once, then reuse it with the same connected evidence mode as the web app.

```bash
bash tools/run_fedora.sh /path/to/lesson.pdf \
  --graph-only --graph-output knowledge-graph.json --progress

bash tools/run_fedora.sh --from-graph knowledge-graph.json \
  --graph-reasoning --syllabus-pdf /path/to/lesson.pdf \
  --questions 10 --difficulty medium --output questions-01.json --progress
```

Use `--syllabus-topic` once per selected ID if you need a restricted scope. The original PDF is optional for a saved graph and makes layout-derived sections available. Use a fresh output path for each CLI run. For a one-shot run, pass the source PDF with `--questions`, `--difficulty`, and `--output` and omit `--graph-only`. Use `--language` to set the requested question language and `--ingest-timeout` to extend the 1,800-second ingestion deadline for long PDFs.

If a CLI run accepts some questions but falls short of the target, it writes the accepted items and exits with status `1`. Use `--resume-questions <partial.json>` together with the same saved graph, scope, difficulty, and reasoning mode, and set `--questions` to the total desired count. An interrupted CLI run exits with status `130`. For QUBO selection on a saved graph, use **Apply QUBO optimisation** in the workspace. The worker's CLI balancing flags collect the candidate pool and checkpoint, and the web server performs final selection.

The CLI uses local inference by default. Hosted CLI mode uses `--provider hosted`, reads `OPENAI_API_KEY` from the environment, and defaults to `gpt-4o-mini`. `OPENAI_BASE_URL` and `--model` can point to a compatible endpoint. Hosted inference sends the materials used in the prompt to that endpoint.

## Stop and resume

- For an active web job, use **Cancel run** and watch the backend window for cleanup. Press `Ctrl+C` in a foreground server terminal or use the printed `kill -TERM <PID>` command for a background server. The PID is also saved in `.kaqg-runtime/web-8765.pid` while the default-port server is running.
- Worker services stop on normal completion or cancellation. After a forced stop, check `podman ps -a --filter name=kaqg-` for containers from the interrupted run. Use `podman stop <container-name>` for a confirmed leftover container.
- To resume after a restart, launch the workspace again and reopen the saved document URL. Graphs and accepted question artifacts are local files. In this checkout, the existing TestMaterial graph is also available in `../TestMaterial/knowledge-graph.json`. See [API and storage](api-and-storage.md) for the server copy.
- The workspace **Relationships** view opens the complete saved graph directly. A separate Neo4j Browser connection requires a running Neo4j instance with that graph loaded. The short-lived ingestion database exits after export.

## Verification

```bash
PYTHONPATH=src .venv/bin/python -m unittest -v unit_test.test_assessment_balance
npm run build --prefix web
```

The focused unit suite covers setting validation, exact and bounded selection, the optional inference deadline, checkpoint publication, and generation with optimisation off. Most upstream AgentFlow integration tests need a configured `kaqg.toml`, broker, model service, or graph instance. Check the requirements in each test before running it.

For a local end-to-end check, upload a small PDF, wait for the graph, and generate a short batch with graph evidence. Confirm the links and answer key in the workspace, then export JSON, CSV, and PDF and open a quiz attempt. With optimisation enabled, confirm the initial quiz is available during collection, inspect the candidate count, and try a short extra-time limit. Keep both log windows open through graph building and question generation to verify that the backend and the local model each show activity.
