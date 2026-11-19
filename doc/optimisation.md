# QUBO optimisation

**Apply QUBO optimisation** is an optional post-generation step. It uses a classical solver on a quadratic binary objective for topic coverage and redundancy. The solver selects whole assessments from the validated pool and keeps their original text, answers, feature scores, and evidence.

## Candidate collection

1. The worker generates and validates the requested `K` questions with the normal syllabus and difficulty. If generation only produces a partial quiz, the usual continuation logic applies before balancing.
2. After reaching `K`, the worker writes a checkpoint through a temporary file and atomic rename. The server watches for the progress marker and publishes the checkpoint as the current quiz. The first quiz is available while extra candidates are evaluated.
3. The worker reuses the same model and evidence queue for extras. Only verified and scored items count toward the extra candidate limit. Collection stops when it reaches that limit, the time limit, or the end of the evidence queue.
4. On Fedora, `ITIMER_REAL` interrupts the optional phase, including a blocking model call. The signal escapes ordinary request error handlers. Already accepted candidates are still written to the pool. The timer covers generation and validation of extras. The short selection and service-cleanup steps run separately.
5. The server writes a selected **Final Set** and publishes the full **Candidate Set**. If the worker fails after creating the checkpoint, the requested quiz remains available. Explicit cancellation can leave the job marked cancelled with its checkpoint still downloadable.

| Setting | Default | Allowed values |
| --- | ---: | --- |
| Apply QUBO optimisation | Off | On or off for the current question job |
| Extra questions | 2 | 1–50 validated extras |
| Max extra time | 30 seconds | 1–3,600 seconds |

The React form sends `balance` and, when enabled, `balance_settings.extra_questions` and `balance_settings.max_seconds`. The values are validated again by the server and the worker. The web server invokes the worker with `--balance-checkpoint`, `--balance-extra-questions`, and `--balance-max-seconds`.

## Objective

Let `x[i]` be 1 if candidate `i` is selected and 0 otherwise. The selector requires exactly `K` selected assessments and distinct normalized stems. It minimizes the sum of a coverage term and a redundancy term.

- **Coverage.** Use named chapter buckets when the pool spans multiple chapters. If the pool has one named chapter, use paths up to the subtopic level. When no named topics are available, use the source pages. Each item divides a share of one equally across its buckets. The target share per bucket is `K / number_of_buckets`. Sum the squared differences between selected and target shares and divide by `K²`. The coverage term is zero when no buckets are available.
- **Redundancy.** For each selected pair, compute the Jaccard overlap of normalized directed graph triples and the Jaccard overlap of stem words. The pair penalty is 75% triple overlap and 25% word overlap when both candidates provide triples. Use word overlap alone otherwise. Divide the sum of pair penalties by the number of selected pairs, with a minimum denominator of one.

Expanding the coverage term produces a linear cost for each candidate and a quadratic cost for every pair. The implementation drops the constant term, which is common to all quizzes for the same candidate pool. The solver enforces cardinality when it evaluates subsets or swaps, so the returned set has exactly `K` items.

## Solver and outputs

- If `C(pool_size, K) ≤ 2,000`, evaluate every eligible subset. Ties use sorted IDs to give a deterministic result for the same candidate pool.
- For larger pools, start with the first `K` distinct candidates. Make up to eight passes, each applying the single swap with the best strictly improving objective change if one exists. The initial quiz remains a feasible starting point and each swap preserves the exact count. The bounded search can end at a local optimum.
- The result records `selection.method` as `exact` or `local-swap`, plus `candidate_count` and `selected_candidate_ids`. The candidate pool includes the first accepted quiz and any validated extras. The displayed number of candidates can be lower than the configured cap if the worker reaches the deadline or runs out of evidence.

The objective currently uses topic or page coverage and overlap. The generator and evaluator are the acceptance gate for question quality. The optimiser receives an already scoped batch at the selected difficulty, so it can choose among those items without changing their difficulty settings.

Implementation lives in [`assessment_selector.py`](../apps/assessment_selector.py), the checkpoint and deadline logic in [`pdf_to_mcq.py`](../apps/pdf_to_mcq.py), and the publication logic in [`serve_web.py`](../apps/serve_web.py). See [question generation](question-generation.md) for validation and [API and storage](api-and-storage.md) for the result contract.
