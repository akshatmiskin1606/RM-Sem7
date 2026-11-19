# API, storage, and exports

[`apps/serve_web.py`](../apps/serve_web.py) serves the React build and the HTTP API from the same loopback origin. Document IDs are lowercase 32-character hexadecimal strings. The server checks the local `Host` header. POST requests require `X-KAQG-Request: 1` and must have a matching origin when an `Origin` header is present.

## HTTP endpoints

| Method and path | Behaviour |
| --- | --- |
| `GET /` | Serves the React workspace from `web/dist` |
| `POST /api/documents` | Accepts raw PDF bytes and starts graph construction. Pass a URL-encoded filename in `X-PDF-Name` or use the default `document.pdf`. The server requires a PDF filename, checks for a PDF signature in the first 1,024 bytes, and limits the body to 100 MiB. Returns `202` with document status. |
| `GET /api/documents/{id}` | Returns filename, graph and question metadata, and the current job status and activity |
| `GET /api/documents/{id}/graph` | Returns the full saved knowledge graph JSON |
| `GET /api/documents/{id}/syllabus` | Returns the derived outline, including its nested branches and selection IDs |
| `POST /api/documents/{id}/questions` | Validates controls and starts a question job on the saved graph. Returns `202` with document status. |
| `GET /api/documents/{id}/questions` | Returns the current question artifact, which can be a partial batch, a checkpoint, or the completed quiz |
| `GET /api/documents/{id}/candidates` | Returns the candidate pool for the current result when it exists |
| `POST /api/documents/{id}/cancel` | Requests cancellation of the active job for that document and returns `202` with status |

For the two question artifact endpoints, append `?format=pdf`, `?format=csv`, or `?format=json` to download the current set as an attachment. The ordinary endpoint returns JSON for the application.

### Question request

```json
{
  "count": 10,
  "syllabus": [],
  "difficulty": "medium",
  "balance": true,
  "balance_settings": {
    "extra_questions": 2,
    "max_seconds": 30
  }
}
```

`count` is required and must be an integer from 1 to 50. An empty or omitted `syllabus` uses the whole document. A nonempty list contains selectable 24-character topic IDs from `/syllabus`. The server deduplicates and sorts them. Difficulty defaults to `medium`, and balancing defaults to `false`. If balancing is enabled, either advanced value can be omitted to use its default. The request body is limited to 512 KiB.

Application errors use `{"error": "…"}`. Typical statuses are `400` for invalid inputs, `403` for disallowed hosts or POST headers, `404` for an unknown document or unavailable artifact, and `409` for an active-job conflict or a question request made before the graph is ready.

## Local state and publication

Each uploaded PDF has a directory at `.kaqg-runtime/web-runs/<id>/` containing these files as applicable.

| File | Purpose |
| --- | --- |
| Original PDF | Source bytes and optional layout metadata for reconstructing the outline |
| `state.json` | Document identity, graph counts, current job and activity, and pointers to the published question artifacts |
| `knowledge-graph.json` | Reusable node and relationship export |
| `graph-summary.json` | Counts and run metadata written by the graph worker |
| `questions-<uuid>.json` | Saved question results, including completed sets and partial results from ordinary runs |
| `quiz-checkpoint-<uuid>.json` | First complete quiz, persisted before collecting extra candidates |
| `candidates-<uuid>.json` | Worker output for an enabled optimisation run. It becomes the candidate pool when the completed final set is published. It can also hold a partial result awaiting continuation. |

`job.stage` is `graph` or `questions`. A `job.status` can be `running`, `complete`, `partial`, `failed`, or `cancelled`. The server can set `job.phase` to `balancing` when it publishes the checkpoint. The state holds the latest job per document. The current artifact pointers include filenames and counts, and a completed optimised quiz adds a `questions.candidates` pointer.

The workspace serializes mutations with a lock and replaces `state.json` atomically. While the worker is running, the status view combines saved metadata with the in-memory activity list. On restart, a saved job with no live worker and a `running` state is reported as cancelled. Cancellation sends `SIGTERM` to the child, which unwinds its cleanup. A checkpoint already on disk can remain available after cancellation or optional-phase failure.

The question JSON contains source PDF, inference provider and model, processed page count, graph summary, requested difficulty, and `assessments`. Syllabus scopes, graph reasoning, `balance_settings`, and `selection` appear as applicable. See [question generation](question-generation.md) and [optimisation](optimisation.md) for assessment fields and selection metadata.

## Export formats

[`apps/question_exports.py`](../apps/question_exports.py) renders a selected artifact on demand.

- **JSON** returns the stored payload with question criteria, evidence, and evaluation metadata.
- **CSV** writes a UTF-8 BOM and one row per question with display number, stem, options A–D, answer letter, and answer text. It prefixes values that spreadsheet programs could otherwise interpret as formulas.
- **PDF** uses PyMuPDF to produce an A4 final set or candidate set with the source name, difficulty when present, grouped choices, and an answer key. It renders from escaped text and writes the document in memory.

Downloads use `questions` or `candidates` as the basename. Exports enumerate the questions in displayed order. The original question IDs remain in the JSON assessment metadata.
