# Question generation and difficulty

The web workflow groups question generation into evidence selection, drafting, independent answer verification, and feature evaluation. A question enters the saved batch after it passes all four steps. Each subsequent generation job can reuse the same graph export.

## Connected evidence

[`graph_reasoning.py`](../apps/graph_reasoning.py) builds an adjacency index from directed fact-to-fact edges in the selected syllabus. Traversal can follow a link in either direction to find connected evidence, while the prompt and result retain the original relation direction. It normalizes fact names to connect repeated entities across pages and excludes self-links and repeated entities within a path. The builder samples up to three completions per oriented starting edge and deduplicates paths by their fact statements.

| UI difficulty | KAQG difficulty code | Feature target | Graph evidence |
| --- | ---: | ---: | --- |
| Easy | 30 | 10 | One relationship across two facts, for direct recall |
| Medium | 50 | 14 | Two relationships across three facts, for combined evidence |
| Hard | 70 | 18 | Three relationships across four facts, preferably across chapters or subtopics |

Hard paths rank evidence from multiple chapters above evidence from multiple named subtopics in one chapter. The queue also prefers less-used edges and topics and deprioritizes document-navigation facts. Cross-topic questions require a suitable connection within the selected syllabus. If the scope contains no path of the requested length, the worker reports an error. It consumes a path even when the candidate is rejected, so a retry uses fresh evidence.

In the direct graph path, [`pdf_to_mcq.py`](../apps/pdf_to_mcq.py) injects `ChatLLM.generate_response()` into the original generator and evaluator handlers. The graph stays in Python and the mode skips MQTT and a fresh Neo4j import. The default local model uses a 768-token output cap and a 160-token override for the structured answer check. The non-graph-reasoning CLI path uses the AgentFlow and Neo4j workflow described in [system architecture](architecture.md).

## Draft, verify, evaluate

1. [`SingleChoiceGenerator`](../src/generation/scq_generator.py) chooses levels 1–3 for the seven features in [`ScqFeatures`](../src/evaluation/features.py). It looks for a weighted sum within one point of the target. The cognitive level has weight 1.5, the high-attraction distractor count has weight 1.2, and the others have weight 1. When a graph path is supplied, its link count determines the target cognitive level. Multi-link items also constrain option length and some similarity and distractor levels.
2. The draft prompt requests one direct stem, four distinct options, and an answer letter in a structured response. The generator validates the stem and options, and asks multi-link questions to use all supplied facts. It prompts with the selected topic when there is one explicit syllabus scope.
3. A separate call to the same model receives the stem and options with the draft key withheld, along with the source evidence and prior stems. It must return exactly one supported option. It checks prior-fact repetition once prior questions exist, checks the explicit topic when applicable, and confirms that all relationships are needed for a multi-link answer. The generator applies the verified key, then shuffles options and updates the key to match their new positions.
4. The worker rejects a repeated normalized stem. [`ScqEvaluator`](../src/evaluation/scq_evaluator.py) grades stem length with a local English/CJK count and requests integer scores from 1 to 3 for the other six features. It validates the returned feature names and scores before accepting the assessment. Requested feature levels and observed evaluation scores can differ.

The seven features are stem length, technical-term density in the stem, cognitive level, average option length, option similarity, stem-to-option similarity, and highly plausible distractor count. The workspace applies these rubrics to the generated items before any learner attempt.

## Batches, retries, and saved evidence

- The worker assigns IDs such as `Q001` from the accepted count. Rejected, invalid, repeated, and unscored drafts do not take a place in the final set.
- The initial worker pass allows three attempts per remaining question, or five when syllabus or page evidence is present. It can stop earlier when evidence is exhausted. The workspace can run one follow-up pass from the accepted partial batch.
- A partial web batch can be continued for the same document, target, syllabus, difficulty, and graph reasoning mode. CLI continuation through `--resume-questions` also checks graph and PDF metadata and validates existing items. An accepted batch reused as a partial input supplies prior stems, answers, and path-use history.
- Each assessment contains `question`, `question_criteria`, and `evaluation`. The criteria record the ID, requested difficulty, feature levels, weighted grade, and, for graph reasoning, `graph_reasoning.nodes` and `graph_reasoning.links`. Links contain `source`, `relation`, `target`, `pages`, and `topic`. `source_pages` gives the combined page references and a single page also produces `source_page`. A selected topic can add `section` and `syllabus_topic`.

Optional [QUBO optimisation](optimisation.md) runs on already accepted assessments. Both the selected quiz and the candidate pool preserve each saved item's wording, answer key, scores, and evidence.
