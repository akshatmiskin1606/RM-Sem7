# KAQG: Knowledge Graph Enhanced Question Generation

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)  
[![Python](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/release/python-3120/)  
[![Docker](https://img.shields.io/badge/docker-ready-blue)](https://www.docker.com/)  

KAQG is a multi-agent system that integrates **Knowledge Graphs**, **Retrieval-Augmented Generation (RAG)**, and **Educational Measurement Theory** (Item Response Theory + Bloom’s Taxonomy) to automatically generate and evaluate exam questions with controllable difficulty.

---

## 📐 System Architecture

[Implementation documentation](doc/README.md) · [System architecture](doc/architecture.md)

**Workflow**:
1. **PdfRetriever** extracts text, concepts, and facts from PDFs.
2. **KnowledgeGraphService** manages Neo4j-based knowledge graphs in Docker.
3. **LlmService** handles LLM-based reasoning and text generation.
4. **SingleChoiceGenerator** creates single-choice questions from KG concepts and facts.
5. **ScqEvaluator** evaluates question quality using feature-based difficulty models.

---

## 📂 Repository Structure

```
src/
 ├─ services/
 │   ├─ llm_service.py          # LLM interface agent
 │   ├─ kg_service.py           # Knowledge graph service
 │   ├─ pdf_retriever.py        # PDF ingestion and KG construction
 │   └─ file_service.py         # File upload service
 │
 ├─ generation/
 │   └─ scq_generator.py        # Single-choice question generator
 │
 ├─ evaluation/
 │   ├─ scq_evaluator.py        # Single-choice question evaluator
 │   └─ features.py             # Difficulty feature definitions
 │
 ├─ knowsys/
 │   ├─ docker_management.py    # Neo4j container orchestration
 │   └─ knowledge_graph.py      # Neo4j graph operations
 │
 ├─ agent.py                    # Core agent framework
 └─ weighted_ranker.py          # Concept ranking with PageRank/TF-IDF
```

> **Note:** directory `evluation/` has been corrected to `evaluation/`.

---

## ⚙️ Environment Setup

### Fedora PDF-to-MCQ baseline

Run these setup commands once from the cloned repository on Fedora x86-64 with
rootless Podman available.

```bash
bash tools/setup_fedora.sh
bash tools/setup_local_model.sh
```

The second command downloads Ollama and Qwen3-VL 4B Instruct for local inference.

#### Use the React workspace

Install the frontend once with `npm ci --prefix web`, then start it with
`bash tools/run_web.sh`. Open [the local workspace](http://127.0.0.1:8765/) in
your browser. Choose a PDF, click **Build graph**, then click **Generate questions**.
The page shows pipeline activity, the interactive graph, and the answer key.
Generating another batch reuses the saved graph. When KAQG returns a partial
batch, the workspace attempts one follow-up pass and keeps the accepted items.

Use **Chapters** to expand the document into chapters, subtopics, and graph
keywords. Check the topics you want under **Syllabus Control** before generating
a batch. A checked chapter includes its descendants. **Clear** restores the
whole-document scope, and **Relationships** opens the interactive edge view.
Use **Download graph** to export the full saved graph as JSON, GraphML, or a ZIP
containing the node and relationship CSV files.

Choose **Easy**, **Medium**, or **Hard** under **Difficulty**. The workspace
uses KAQG's native difficulty and evaluation features with one, two, or three
connected graph relationships. Hard prefers paths across topics when the
selected syllabus supports them. Each question shows its graph evidence.
For these batches, KAQG reads the graph export directly and uses a fresh path
when a candidate fails validation.

Enable **Apply QUBO optimisation** to save the requested quiz first, then look for
extra validated candidates. Under **Advanced settings**, set the extra question
limit (1–50, default 2) and the time limit for generating and validating extras
(1–3600 seconds, default 30). Collection stops when either limit is reached or
the graph runs out of distinct evidence. The classical solver favours topic
coverage and penalises overlap. It evaluates all subsets when there are up to
2,000 combinations and uses a bounded swap search for larger pools. The **Final
Set** and **Candidate Set** share the original wording and answer keys and can
both be downloaded. The checkbox defaults to off.

Uploads and results are under `.kaqg-runtime/web-runs/`. The workspace uses the
local model and binds to `127.0.0.1`. Use **Cancel run** to stop a job. Press
`Ctrl+C` in the launcher to close the workspace, or run the stop command printed
at startup if you used `bash tools/run_web.sh --background`.

For live logs on Fedora with Konsole, run `python3 tools/open_log_terminals.py`
from this folder. **KAQG Backend** follows the workspace and its pipeline
processes. **Qwen Model** follows Ollama's model loading and inference output.
The windows keep following new runs. Close either window to stop viewing its log.

#### Use the command line

This command uploads a PDF and returns three English multiple-choice questions,
answer letters, and KAQG evaluation scores.

```bash
bash tools/run_fedora.sh "/path/to/lesson.pdf" --questions 3 --output questions.json
```

The launcher creates a temporary graph for one PDF per run. Neo4j, Mosquitto, and
Ollama listen on loopback and are stopped when the command finishes or is
interrupted. The JSON includes graph counts, target and observed question
features, and answers. The launcher checks generated answer keys and screens for
repeated topics before scoring each question. Use `--difficulty easy|medium|hard` and
`--language` to change the defaults. For long PDFs, increase
`--ingest-timeout` from its default of 1,800 seconds.
If KAQG verifies fewer items than requested, it saves the accepted items and
exits with status 1.

#### Build a graph once and reuse it

Use `--graph-only` to extract the PDF into a reusable graph file. The command
stops after saving the nodes, relationships, and their properties.

```bash
bash tools/run_fedora.sh "/path/to/lesson.pdf" \
  --graph-only --graph-output knowledge-graph.json --progress
```

Use `--from-graph` whenever you want another question batch. The launcher reads
the saved graph into temporary Neo4j and starts at question generation. It needs
only the graph JSON. Pick a new `--output` path for each batch.

```bash
bash tools/run_fedora.sh --from-graph knowledge-graph.json \
  --questions 10 --difficulty medium --output questions-01.json --progress
```

Each question includes its answer letter and KAQG feature scores. The graph
file stays on disk between runs and the temporary services stop after each run.
To continue a partial batch, pass its JSON file with `--resume-questions`, use
the same saved graph, and pick a fresh output filename. `--questions` is the
total to reach, including the items already in the partial batch.

The local backend requires no API key. For the upstream OpenAI backend, set
`OPENAI_API_KEY` privately in your terminal and add `--provider hosted`. The
default hosted model is `gpt-4o-mini`. You can also set `OPENAI_BASE_URL` and
`--model` for an OpenAI-compatible endpoint. Hosted mode sends extracted
PDF content to the endpoint you configure.

The local smoke test used upstream commit `aa80de0082d5c217bbcb887ba386c2a85518c7d6`
with the Fedora changes in this checkout, Python 3.12.16, Neo4j 5.26.33,
Eclipse Mosquitto 2.0, and Ollama 0.40.16 with `qwen3-vl:4b-instruct`. The
two-page text PDF produced 17 concepts, 41 facts, 119 relationships, and two
scored questions. The sample PDF, JSON output, and resolved Python versions are
under `.kaqg-runtime` on this machine.

### Requirements
- Python **3.12+**
- Docker (for Neo4j containers)
- Mosquitto (MQTT broker)
- Recommended: **16GB RAM**, optional **GPU** if using local LLMs

### Installation

```bash
git clone https://github.com/mfshiu/kaqg.git
cd kaqg

conda create -n kaqg python=3.12
conda activate kaqg
pip install -r requirements.txt
```

### Configuration

```bash
cp kaqg-sample.toml kaqg.toml
# Edit kaqg.toml based on your environment
```

### Start MQTT Broker (Example on Windows)

```bash
cd "C:\Program Files\mosquitto"
mosquitto -c mosquitto.conf
```

---

## 🧩 Core Services

### **FileService**
- **One-line**: Manages file upload and metadata storage.  
- **Details**: Handles binary files, extracts metadata (filename, type, encoding), and provides access to subsequent processing agents.

---

### **LlmService**
- **One-line**: Provides LLM-powered text generation.  
- **Details**: Supports ChatGPT, Claude, and LLaMA via a unified API. Subscribes to `Prompt/LlmService/Services` and responds with generated content.

---

### **KnowledgeGraphService**
- **One-line**: Creates and manages knowledge graphs in Docker-hosted Neo4j.  
- **Details**: Supports container lifecycle (create, open, stop) and enables queries such as **concepts**, **facts**, and **sections**. Subscribes to `KGService/Services` topics.

---

### **PdfRetriever**
- **One-line**: Extracts facts and concepts from PDFs into the knowledge graph.  
- **Details**: Uploads PDFs, extracts triplets (fact–relation–concept), and stores them in Neo4j. Supports section hierarchy mapping from document TOC.

---

### **SingleChoiceGenerator**
- **One-line**: Generates single-choice exam questions from KG concepts and facts.  
- **Details**: Uses **rankers** (PageRank, TF-IDF, domain-specific) to select concepts/facts, then prompts LLMs to generate structured questions. Ensures difficulty calibration with feature-based scoring.

---

### **ScqEvaluator**
- **One-line**: Evaluates difficulty and validity of generated questions.  
- **Details**: Uses 7 linguistic and structural features (stem length, option similarity, distractor plausibility, etc.) weighted by IRT + Bloom’s Taxonomy to validate question quality.

---

## 🚀 Quick Start Example

### 1. Upload PDF
```python
# Publish a PDF file to be processed
agent.publish("FileUpload/Pdf/Retrieval", {
    "kg_name": "WasteManagement",
    "file": "waste_regulations.pdf"
})
```

### 2. Generate Question
```python
criteria = {
    "question_id": "Q101",
    "subject": "WasteManagement",
    "document": "Regulation Book",
    "section": ["Chapter 1", "Subsection 1.1"],
    "difficulty": 50
}
agent.publish("Create/SCQ/Generation", criteria)
```

### 3. Evaluate Question
```python
agent.publish("Evaluate/SCQ", {"question_id": "Q101"})
```

---

## 📊 Example Workflow

```
PDF → PdfRetriever → KnowledgeGraphService (Neo4j) → 
Concepts/Facts → SingleChoiceGenerator → Draft Questions →
ScqEvaluator → Validated Exam Items
```

---

## 📚 References

- Lewis et al., *Retrieval-Augmented Generation for Knowledge-Intensive NLP* (2020)  
- Yu et al., *GraphRAG: RAG Meets Knowledge Graphs* (2024)  
- Shiu et al., *KAQG: A Knowledge Graph Enhanced RAG for Difficulty Controlled Question Generation* (2025, under review)

---

## 🤝 Contributing
Pull requests and issues are welcome. Please ensure tests are included for new features.

---

## 📄 License
This project is licensed under the [MIT License](LICENSE).
