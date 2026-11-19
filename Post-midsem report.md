# Final report additions and replacement text

## Placement in the mid-sem report

| Existing location | Update for the final report |
| --- | --- |
| Abstract and §1.4–§1.6 | Describe the implemented PDF workspace and its contributions. Update the chapter summary. |
| Chapter 2 and Chapter 3 | Keep the literature review and the original KAQG architecture. Add the project-specific gap to §2.5 and keep the difficulty hypothesis in §3.3. |
| §4.1 and Figure 4.1 | Replace the proposed data flow with the two actual execution paths. Use the original broad architecture as a labelled mid-sem design figure only if needed for context. |
| §4.2–§4.4 | Add the concrete scope resolution, graph path controls, answer verification, and scoring rules. Keep Figures 4.2 and 4.3 as conceptual illustrations or replace them with annotated screenshots and a saved evidence path. |
| §4.5 and Figure 4.4 | Replace the proposed 500-to-50 and QAOA pipeline with the implemented binary objective, classical solver, and checkpoint. |
| Chapter 5 | Rename it **Implementation and Evaluation**. Update the phase table, use §5.2 for runtime tuning, and split completed verification from planned evaluation. The original timeline can move to an appendix. |
| Chapter 6 | Replace proposal language and guarantees with findings from the working prototype and the remaining evaluation questions. |

The bibliography uses a different numbering order from the slides. In the current report, KAQG is [3], KNIGHT is [1], Lucas is [7], and Farhi et al. is [4]. Keep the LaTeX citation keys when copying the text, then regenerate the references and list of figures.

## Replacement abstract

This project implements a syllabus-aware multiple-choice question generation platform on the KAQG framework. A teacher uploads a PDF, builds a reusable knowledge graph, and selects the chapters or topics eligible for assessment. The system resolves the selections to permitted fact relationships before constructing the context. Easy, Medium, and Hard settings use paths of one, two, and three relationships, respectively. Hard generation prioritises cross-chapter paths when approved sections contain connected evidence. A separate answer-check prompt and KAQG’s feature evaluator screen candidates before the quiz is saved. An optional QUBO-based selection stage runs on the CPU and uses validated questions to improve topic coverage and reduce redundancy under a fixed quiz size. In a 12-page study-notes example, the system stored 1,253 nodes and 3,834 relationships. In one saved assessment run, the selector chose 10 questions from 15 candidates and reduced the implemented objective from 0.1602 to 0.0560 relative to the first 10 accepted questions. The results establish feasibility on the local prototype and motivate broader evaluation of item quality and difficulty with instructors and learners.

## §1.4–§1.6 — Implemented solution and contributions

The implemented platform separates PDF ingestion from assessment generation so that one saved graph can support different syllabus selections and repeated question batches. Teacher selections are resolved to permitted evidence before generation. The selected difficulty determines the number of connected relationships provided to the generator and the target cognitive level in KAQG’s item features. Accepted questions retain their answer keys, feature scores, and supporting graph paths. An optional post-generation selector constructs a fixed-size quiz from a larger validated pool.

Use these contribution statements in §1.5.

1. **Teacher-defined evidence scopes.** The platform maps a document hierarchy to fact relationships and restricts context construction to the teacher’s selected scopes.
2. **Difficulty-controlled evidence construction.** The platform combines configurable graph path lengths with KAQG’s feature targets and checks the use of multi-link evidence in generated items.
3. **Local assessment assembly.** The platform publishes the first validated quiz and optionally improves balance through classical selection with a quadratic binary objective and a configurable inference budget.

In §1.6, say that Chapter 4 describes the implemented architecture and methods, Chapter 5 documents the phases and preliminary verification, and Chapter 6 concludes with the capabilities demonstrated and the evaluation still required.

## Addition to §2.5 — Project-specific novelty

KAQG supplies graph-grounded item generation and difficulty-related feature targets. KNIGHT demonstrates reusable topic graphs and multi-hop, instructor-controlled question generation. The contribution of this project is the integration of these ideas in a teacher-facing PDF workflow. The teacher’s selection determines eligible edges before path construction, the selected difficulty changes the structure of the permitted evidence, and accepted items can feed a fixed-size coverage and redundancy objective. The novelty claim concerns this workflow and its controls. [KAQG paper](https://doi.org/10.1109/ACCESS.2025.3633838) · [KNIGHT paper](https://proceedings.mlr.press/v328/amanlou26a.html)

## §4.1 — Implemented architecture and data flow

The implementation has two execution paths. In the ingestion path, the React workspace submits a PDF to a local Python HTTP server. The worker prepares Ollama with `qwen3-vl:4b-instruct`, and starts temporary Mosquitto and Neo4j services under rootless Podman. The KAQG retrieval workers extract page text and, when present, describe tables or images. They write concepts, facts, provenance, and directed relationships to Neo4j. The runner exports the graph as JSON before the temporary services stop.

In the assessment path, the worker opens the saved graph export and derives allowable evidence paths from the instructor’s syllabus and difficulty settings. It invokes KAQG’s single-choice generator and evaluator directly with a local model adapter. Questions and their evidence are saved by the workspace. Graph history lets the teacher reopen earlier graphs for exploration, export, and future batches. The React workspace shows job progress and supports answer review, a practice attempt, and exports of the graph and question sets.

**Figure 4.1 replacement caption** “Implemented architecture showing one-time PDF graph construction and repeated assessment generation from the saved graph.” Show the syllabus and difficulty controls entering the evidence-path component, and place optional QUBO-based selection after validation. Label the served inputs and implemented dependencies according to this PDF workflow. [Implementation architecture](kaqg/doc/architecture.md)

## §4.2 — Syllabus-constrained retrieval

The system reconstructs the document outline from bookmarks or layout-derived headings when the PDF provides them. It can fall back to Neo4j structural relationships or to page groups. Each selectable branch resolves to fact edges with source pages. Selecting a parent branch includes its descendants. For a restricted request, the system enumerates candidate paths only over the union of the selected edge scopes. The same saved graph can therefore support multiple assessment scopes without re-ingesting the document.

The boundary is enforced on the evidence supplied to generation. The saved question links expose the originating topics and pages for review. A separate model check also assesses whether an item directly tests the selected topic when generation receives a single explicit scope. In an example with Sessions 2 and 5 selected, the accepted Hard question linked evidence about Manthara and mind on page 5 with the chariot model on page 7. [Syllabus implementation](kaqg/doc/knowledge-graph.md) · [Saved example](kaqg/.kaqg-runtime/web-runs/46c67bcc55fb70a0859c0afb633be9ab/questions-3d75760729194894b1242c3529f36d8e.json)

## §4.3 — Difficulty-aware context and cross-chapter integration

Difficulty is controlled through the evidence path and through KAQG’s existing question features. Easy supplies one directed relationship between two facts and targets recall. Medium supplies two connected links between three facts. Hard supplies three links between four facts and prioritises paths with evidence from different approved chapters, then paths spanning subtopics within an approved chapter. The original relationship directions and source pages are retained in the prompt and output even when a path is discovered by traversing an edge in reverse. The link count fixes the requested cognitive feature level for graph-based items. The other features are chosen within KAQG’s target score range.

Cross-chapter reasoning depends on having a connected path within the selected scopes. A Hard question can use a connected path within one chapter when the approved scope supports that path. When no suitable path exists at the requested length, the system asks the user to widen the scope or choose a lower level. These settings control the evidence supplied and the intended reasoning demand. Item difficulty for learners remains an empirical question. [Question generation implementation](kaqg/doc/question-generation.md)

## §4.4 — Question validation and candidate management

KAQG first drafts a question with four distinct options and an answer. A second prompt receives the question and source evidence with the draft key withheld. It accepts one supported option, screens repeated facts, and checks that a multi-link question requires all supplied links. The verifier and generator use the same local model in separate calls. The pipeline uses the verified key when shuffling the options and rejects repeat stems before feature evaluation.

KAQG’s evaluator assigns scores to seven item features. It computes stem length locally and uses a structured model response for the other six. Invalid or unscored candidates are skipped. The workspace keeps accepted items and can perform a follow-up pass on a partial result. The saved assessment records separate requested and evaluated features as well as the graph evidence used for the question. [Generation and validation details](kaqg/doc/question-generation.md)

## §4.5 — QUBO-based assessment optimisation

For a pool of $N$ validated candidates, let $x_i \in \{0,1\}$ indicate whether candidate $i$ is selected. The quiz must contain exactly $K$ items with distinct normalized stems. Let $B$ be the topic buckets present in the pool, and let $w_{ib}$ be the fraction of item $i$’s evidence share assigned to bucket $b$. Each item divides one unit across its matched buckets. The selector uses chapters when several are represented, subtopics for a single named chapter, and source pages when the pool has no named topics. For each pair, $r_{ij}$ is 0.75 times the Jaccard overlap of directed graph triples plus 0.25 times the Jaccard overlap of stem words. Word overlap alone is used when either candidate lacks triples.

Replace the proposed objective in Eq. 4.1 with the implemented objective. Here is a LaTeX block for it.

```latex
\begin{equation}
\min_{x} J(x) =
\frac{1}{K^2}\sum_{b\in B}
  \left(\sum_{i=1}^{N} w_{ib}x_i - \frac{K}{|B|}\right)^2
+ \frac{1}{\max\{1,\binom{K}{2}\}}
  \sum_{i<j} r_{ij} x_i x_j.
\end{equation}
```

The coverage term is zero when no evidence buckets are available. The expansion is quadratic because $x_i^2=x_i$ for binary variables. Retain the exact cardinality condition $\sum_i x_i = K$ in Eq. 4.2. The classical solver enforces it when enumerating or swapping items. An unconstrained QUBO representation could instead encode it with a sufficiently large penalty $\lambda(\sum_i x_i-K)^2$. [Ising and QUBO reference](https://doi.org/10.3389/fphy.2014.00005) · [Selector implementation](kaqg/doc/optimisation.md)

The solver evaluates every feasible subset when the total number of combinations is at most 2,000 and uses up to eight improving single-item swaps for larger pools. The user can cap the count and duration of optional candidate generation. The defaults are two extras and 30 seconds. The worker publishes the first complete quiz as a checkpoint before generating extras and retains it if the time budget expires. The final and candidate sets preserve original answers, wording, and evidence. This is the local classical baseline for a future QAOA comparison on the same candidate pools. [QAOA paper](https://arxiv.org/abs/1411.4028)

**Figure 4.4 replacement caption** “The first validated quiz is published before optional extra-candidate collection. The classical selector then ranks eligible fixed-size subsets using coverage and pairwise overlap.”

## §5.1 — Implementation phases

| Phase | Implemented output and evidence |
| --- | --- |
| 1. KAQG reproduction | Local PDF ingestion and question generation with Fedora, Podman, Neo4j, and Ollama |
| 2. Material upload and graph view | React upload, saved graph, browsable chapter hierarchy, graph labels, and exports |
| 3. Syllabus enforcement | Teacher-selected branches resolve to eligible fact edges with page provenance |
| 4. Difficulty control | One-, two-, and three-link paths plus native KAQG cognitive and item-feature targets |
| 5. Cross-chapter generation | Hard paths prefer links from multiple approved chapters and store the link-level evidence |
| 6. Validation and candidate management | Answer verification, duplicate screening, feature scores, saved accepted items, and downloads |
| 7. Classical QUBO-based assembly | Checkpoint, configurable extra-candidate collection, exact or bounded selection, and separate final and candidate sets |

## §5.2 — Runtime tuning

The short-batch development comparison used the same saved graph, Session 1 scope, Qwen model, Hard setting, and target of five accepted items. The initial run took approximately 5 min 33 s and the tuned run approximately 2 min 10 s, about 61% lower elapsed time in this pair. The tuned path reads the graph JSON directly and invokes the generator and evaluator without restarting Neo4j and MQTT. It caps the default local draft at 768 tokens and the structured answer check at 160 tokens. It consumes fresh graph evidence after rejected candidates. It retains the requested three-link path depth and evaluation before acceptance. Both recorded runs began with the graph already built. The observed difference reflects the combined tuning. [Before run](kaqg/.kaqg-runtime/web-runs/9808025b04989cd7dafbdf1a9ba54416/questions-9d79a716c9d048ee8576e2679f0f93a8.json) · [Tuned run](kaqg/.kaqg-runtime/web-runs/46c67bcc55fb70a0859c0afb633be9ab/questions-92fa27649d9d4ae7b04f404e0a40f1a6.json) · [Local HTTP log](kaqg/.kaqg-runtime/web-8765.log)

## §5.3 — Prototype verification

| Check | Recorded result | Interpretation |
| --- | --- | --- |
| PDF graph and export | 12 processed pages, 1,253 nodes, 3,834 relationships | The saved graph supported repeated question generation and export. |
| Cross-chapter Hard generation | One accepted item with three links across selected Sessions 2 and 5 | The implementation can produce and expose a cross-chapter evidence path. |
| Exact selection and deadline | With a 60-second budget, three extras produced a five-item pool and the exact selector returned two. With a one-second budget, the two-question checkpoint remained available. | The extra-count and time caps operate separately from the required quiz size. |
| Ten-question optimisation | 15 validated Medium candidates, 10 selected via bounded swaps | The first 10 scored 0.1602 and the selected 10 scored 0.0560 under the same objective and candidate pool. |

In the ten-question example, Sessions 1–4 were approved, and the pool represented named evidence from Sessions 1, 3, and 4. Their counts shifted from 6, 3, and 1 to 4, 4, and 2. The calculated coverage penalty fell from (0.1267) to (0.0267), and the average pairwise redundancy penalty fell from (0.0336) to (0.0294). The first quiz was saved about 93 seconds before the final set, including extra generation, selection, and publication. The improvement measures the programmed objective for this one pool. Assessment quality and coverage across all approved chapters require separate evaluation. [Graph export](TestMaterial/knowledge-graph.json) · [First 10](kaqg/.kaqg-runtime/web-runs/9808025b04989cd7dafbdf1a9ba54416/quiz-checkpoint-0bc0f419149c41a08184101188907f1d.json) · [Pool of 15](kaqg/.kaqg-runtime/web-runs/9808025b04989cd7dafbdf1a9ba54416/candidates-a1ec8cb38943428d87c797d9fd935a72.json) · [Selected 10](kaqg/.kaqg-runtime/web-runs/9808025b04989cd7dafbdf1a9ba54416/questions-4136070fed9e49b9b5589627d6316f35.json)

## §5.4–§5.5 — Evaluation protocol and future work

Evaluate scope fidelity on several PDFs and selected syllabi. First test that every recorded evidence edge comes from an eligible scope. Then ask independent reviewers to judge whether the final question and answer actually assess the selected material. Report the accepted count, out-of-syllabus rate, and ambiguous-answer rate with the number of items reviewed.

To test the difficulty hypothesis, generate Easy, Medium, and Hard items from the same documents and comparable topic scopes over multiple runs. Ask reviewers who cannot see the requested level to rate reasoning demand, then report agreement and the difference between requested and rated levels. Collect learner responses for empirical difficulty or IRT analysis. Report end-to-end question runtime separately from graph-build latency and selector-only time, with the model, scope, requested count, and hardware held fixed during runtime comparisons.

For optimisation, compare the first accepted subset, greedy selection, exact enumeration when feasible, bounded swaps, and a simulated QAOA experiment on identical pools and objective settings. Compare the objective, number of feasible solutions, topic coverage, redundancy, and selector runtime. Mixed difficulty and Bloom-level quotas with explicit feasibility checks are further work. [QAOA paper](https://arxiv.org/abs/1411.4028)

## Chapter 6 — Replacement conclusion

The prototype extends the KAQG PDF workflow with teacher-defined evidence scopes, difficulty-controlled graph paths, and optional fixed-size assessment assembly. The saved graph supports repeated local question batches, and each accepted graph-based item retains the links and pages that support it. The recorded runs demonstrate cross-chapter generation within selected scopes, lower elapsed time after engineering tuning in one matched development comparison, and an improved coverage and redundancy objective for one saved candidate pool. These results support the feasibility of the implementation. Repeated tests with independent item ratings and learner responses can establish how consistently the controls translate into syllabus relevance and educational difficulty.
