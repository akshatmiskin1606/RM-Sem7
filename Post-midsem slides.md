# Final presentation additions

The mid-sem deck has 22 slides. Keep slide 11 as the **original KAQG architecture** and slide 14 as the **mid-sem proposal**. In the final deck, use slides 15–23 below in place of old slides 15–19. This keeps the syllabus, difficulty, validation, and optimisation topics in the same part of the story and replaces the proposed implementation strategy with completed work. Update the old Future Work slide as slide 24, add the conclusion as slide 25, and move the two reference slides to 26–27. Update the contents on slide 2. The numbering below follows that layout.

In the existing slides, keep the related-work attribution for KAQG and KNIGHT. State the novelty as an extension of the KAQG workflow. KAQG already targets difficulty, and KNIGHT already uses reusable graphs and multi-hop paths. In your project, the teacher's syllabus controls which fact edges may enter the path search, and the validated items feed an optional fixed-size assessment selector. [KAQG paper](https://doi.org/10.1109/ACCESS.2025.3633838) · [KNIGHT paper](https://proceedings.mlr.press/v328/amanlou26a.html)

## Slide 15 — Implementation phases

Use a short roadmap with the seven phase numbers from the original implementation strategy.

| Phase | Completed work |
| --- | --- |
| 1 | Reproduced the KAQG baseline with local Qwen inference on Fedora. |
| 2 | Built the React PDF upload and saved graph explorer. |
| 3 | Mapped chapters and subtopics to graph evidence and enforced the teacher’s syllabus before path search. |
| 4 | Mapped Easy, Medium, and Hard to one, two, and three evidence links and tuned the generation loop. |
| 5 | Prioritised paths spanning selected chapters for Hard questions. |
| 6 | Verified answers, screened repeated facts, scored items, and kept accepted candidates. |
| 7 | Added optional QUBO-based selection of the final set. |

## Slide 16 — Phases 1–2 · Local baseline and reusable graph

- KAQG’s PDF retriever builds fact and concept relationships in Neo4j using local `qwen3-vl:4b-instruct` inference.
- The workspace saves the full graph as JSON after ingestion. Questions can then be generated repeatedly from that graph.
- The TestMaterial PDF produced **1,253 nodes and 3,834 relationships across 12 processed pages**.

**Visual** Use a two-lane diagram. Top lane: PDF → PyMuPDF and KAQG extraction → Neo4j → saved graph JSON. Bottom lane: saved graph JSON → scoped graph paths → KAQG generator and evaluator → saved quiz. Mark the top lane **per PDF** and the bottom lane **per question batch**. Neo4j and the MQTT broker run during graph building. The web question path reads the export directly in Python.

## Slide 17 — Phase 3 · Syllabus control at retrieval

- A teacher can select chapters, subtopics, or graph keywords in the React outline. Selecting a chapter includes its descendants.
- The outline comes from PDF headings or bookmarks, with graph sections and then page grouping as fallbacks.
- The selected branches resolve to allowed fact edges **before** the path search. The saved evidence records the topic and source pages for each link.

**Visual** Show the actual **Chapters** and **Syllabus Control** panels. Select Sessions 2 and 5 for the next slide’s example. Put the three steps under the screenshot: `Select chapters → Allow only their edges → Generate from those edges`.

## Slide 18 — Phases 4–5 · Graph-based difficulty and cross-chapter reasoning

| Difficulty | Evidence per question | Target task |
| --- | --- | --- |
| Easy | 1 link, 2 nodes | Recall a direct relationship |
| Medium | 2 links, 3 nodes | Combine related facts |
| Hard | 3 links, 4 nodes | Integrate three facts, across approved chapters when the graph supports it |

Show the saved Hard example under the table. **Session 2, p. 5** gives *Manthara maps to mind*. **Session 5, p. 7** gives *mind is the reins in The Chariot Within* and *intelligence is the charioteer in The Chariot Within*. The accepted answer combines all three relationships. [Saved cross-chapter question and evidence](kaqg/.kaqg-runtime/web-runs/46c67bcc55fb70a0859c0afb633be9ab/questions-3d75760729194894b1242c3529f36d8e.json)

**Speaker note** The saved stem asks, “Which of the following correctly integrates the metaphors of intelligence, mind, and Manthara as presented in the provided texts?” Its answer is D, “Intelligence is the charioteer, mind is the reins, Manthara maps to mind.” The graph length controls the evidence the model receives. Learner data would be needed to determine the actual difficulty of the items. Multi-hop generation itself is prior work. [KNIGHT paper](https://proceedings.mlr.press/v328/amanlou26a.html)

## Slide 19 — Phase 6 · Question verification and scoring

Use one horizontal flow with four steps.

1. **Draft** one question and four distinct options from the selected evidence.
2. **Verify** the answer with a separate Qwen prompt that receives the question without the draft key. Screen for repeated facts and require all links for multi-link items.
3. **Score** the item with KAQG’s seven-feature evaluator.
4. **Keep or retry**. Save accepted items with the answer and evidence. Try a fresh path when a candidate fails.

**Speaker note** Generation and verification are separate calls to the same model. The feature scores and verifier give automated signals for review.

## Slide 20 — Runtime tuning for Hard generation

- Reused the saved graph directly and called KAQG’s generator and evaluator without bringing up Neo4j and MQTT again for each question job.
- Capped Qwen’s draft output at **768 tokens** and the structured answer check at **160 tokens**.
- Changed retries to move to fresh graph evidence after a rejection. The three-link evidence requirement, answer check, and evaluator still apply.

**Visual** Two bars, **5 min 33 s before** and **2 min 10 s after**. Caption: “Time to five accepted Hard questions on the same saved TestMaterial graph and Session 1 scope, using the same local model. One development run per configuration, graph construction excluded.” Use “about **61% lower elapsed time**” only with that caption. This comparison covers the changes together. [Before run](kaqg/.kaqg-runtime/web-runs/9808025b04989cd7dafbdf1a9ba54416/questions-9d79a716c9d048ee8576e2679f0f93a8.json) · [Tuned run](kaqg/.kaqg-runtime/web-runs/46c67bcc55fb70a0859c0afb633be9ab/questions-92fa27649d9d4ae7b04f404e0a40f1a6.json) · [Local HTTP log](kaqg/.kaqg-runtime/web-8765.log)

## Slide 21 — Phase 7 · QUBO-based quiz selection

- For each validated candidate, use a binary decision `xᵢ` to include it in the quiz. Choose exactly the requested number of items.
- Minimise deviation from even topic coverage and penalise pairs with overlapping evidence or similar stems.
- Evaluate all eligible subsets for up to **2,000 combinations**. For larger pools, use a bounded classical swap search.
- The checkpoint quiz is available before optional candidate collection. Default budget is **2 extras within 30 seconds**, configurable by the user.

**Speaker note** Use the title **QUBO-based assessment optimisation**. QUBO supplies the quadratic binary model. The implemented solver runs locally on the CPU, and a QAOA comparison belongs on Future Work. [Ising and QUBO formulation](https://doi.org/10.3389/fphy.2014.00005) · [QAOA](https://arxiv.org/abs/1411.4028)

## Slide 22 — Assessment selection on TestMaterial

**15 validated candidates → 10 Medium questions**

| Same candidate pool | Session 1 | Session 3 | Session 4 | Objective ↓ |
| --- | ---: | ---: | ---: | ---: |
| First 10 accepted | 6 | 3 | 1 | 0.1602 |
| Selected 10 | 4 | 4 | 2 | 0.0560 |

- The bounded swap search selected the final set. The five extra candidates and final publication took about **93 s after the first quiz was saved**, within the configured 120-second inference window.
- Sessions 1–4 were approved. The candidate pool supplied named evidence from Sessions 1, 3, and 4. Coverage is measured over evidence represented in the pool.

**Visual** Plot the two rows as grouped bars by session. Footnote: “One saved run. Objective values computed on the same candidate pool. Lower is better under the implemented coverage and overlap objective.” [Candidate pool](kaqg/.kaqg-runtime/web-runs/9808025b04989cd7dafbdf1a9ba54416/candidates-a1ec8cb38943428d87c797d9fd935a72.json) · [First quiz](kaqg/.kaqg-runtime/web-runs/9808025b04989cd7dafbdf1a9ba54416/quiz-checkpoint-0bc0f419149c41a08184101188907f1d.json) · [Selected quiz](kaqg/.kaqg-runtime/web-runs/9808025b04989cd7dafbdf1a9ba54416/questions-4136070fed9e49b9b5589627d6316f35.json)

## Slide 23 — Workspace and demonstration

- Open the existing TestMaterial graph from **Graph history** and show its **Chapters** and **Relationships** views.
- Select a syllabus, choose a difficulty, and open a saved question’s graph evidence and answer key.
- Show **Final Set** and **Candidate Set** and the quiz mode. The graph exports as JSON, GraphML, or node and edge CSV files. Questions export as PDF, CSV, or JSON.

**Demonstration note** Use the saved artefacts for the graph and optimisation result. Start a small new batch if time permits. Show the **KAQG Backend** and **Qwen Model** terminals during that live batch.

## Slide 24 — Future work

Update the existing slide so the remaining research follows directly from the implementation.

- Ask instructors to rate relevance, answer quality, and reasoning demand across several PDFs and difficulty settings.
- Test mixed difficulty and Bloom-level quotas within a single assessment.
- Compare first accepted, greedy, exact, bounded swap, and simulated QAOA on identical candidate pools. Record constraint satisfaction, objective score, and selector runtime.

## Slide 25 — Contributions and conclusion

- **Syllabus control.** A teacher’s selection determines the eligible graph edges before context is built.
- **Difficulty control.** The same syllabus boundary supports one-, two-, and three-link evidence paths and traceable cross-chapter questions.
- **Assessment assembly.** A configurable classical QUBO-based stage chooses a fixed-size set from verified candidates without delaying publication of the first quiz.

The prototype runs PDF ingestion, question generation, validation, and assessment assembly locally. Its saved evidence makes the decisions inspectable at the question and quiz levels.
