# Knowledge graph and syllabus

Graph construction happens once per uploaded document. The workspace stores the full Neo4j export and derives a separate chapter outline and question scopes from it.

## Ingesting a PDF

1. The web server saves the upload and starts `pdf_to_mcq.py --graph-only`. A temporary Podman socket provides the Docker-compatible API used by `KnowledgeGraphService`. The runner starts Mosquitto and Neo4j and waits for the required workers to connect.
2. `PdfRetriever` receives a binary parcel on `FileUpload/Pdf/Retrieval`. It hands the bytes and metadata to `FileService`, then invokes `PdfImport.extract_content()` on the staged file.
3. `extract_pdf_contents()` uses PyMuPDF to extract page text, tables, and embedded images. The image path skips images with at most 10,000 pixels. The extractor sends larger images and Markdown representations of tables to the configured model for descriptions. It merges the resulting text fragments in page order so graph facts retain physical PDF page provenance.
4. For each readable page, `PdfRetriever` asks the model for entities, concept groups, and fact relationships. It adds the structural triplets and sends the page's combined triplets to `KnowledgeGraphService` over MQTT. A failed page can be retried twice with shorter passages of approximately 1,400 and 950 characters. Empty pages are skipped. A retained failure prevents the workspace from publishing a ready graph.
5. The runner uses Cypher to read all nodes and directed edges into `knowledge-graph.json`. It also saves counts in `graph-summary.json` for web graph builds. Neo4j and the other temporary services stop when the job exits.

The ingestion path is implemented in [`pdf_to_mcq.py`](../apps/pdf_to_mcq.py), [`pdf_retriever.py`](../src/retrieval/pdf_retriever.py), [`pdf_extractor.py`](../src/retrieval/pdf/pdf_extractor.py), and [`kg_service.py`](../src/services/kg_service.py).

## Graph schema

| Node label | Meaning and properties |
| --- | --- |
| `document` | Document root with a name, source file ID, and serialized metadata when present |
| `structure` | Section or subsection from the ingestion hierarchy |
| `concept` | A grouping for related facts with a name and optional aliases |
| `fact` | A named fact or entity with a source file ID, optional aliases, and zero-based `page_number` |

| Relationship | Direction |
| --- | --- |
| `part_of` | A section points to its enclosing section or document |
| `include_in` | A concept points to the appropriate section or document |
| `is_a` | A fact points to a concept |
| Extracted relation type | A source fact points to a target fact using the model-supplied relationship name |

[`KnowledgeGraph.add_triplets()`](../src/knowsys/knowledge_graph.py) creates facts per file and page, merges named structural and concept nodes, and merges edges. The same named fact can occur on multiple pages. The connected-path builder uses normalized fact names to connect evidence across those instances while keeping each original directed triple and its provenance in the question.

The export contains `pdf`, `processed_pages`, `failed_pages`, `nodes`, and `relationships`. Each node contains `id`, `labels`, and `properties`. Each relationship contains `source`, `target`, `type`, and `properties`. Endpoint IDs refer to nodes in that export. The runner rejects a reuse file with failed pages, missing core data, or invalid endpoint references when validating or restoring it. A Neo4j restore creates new internal IDs and builds an old-to-new ID map before restoring relationships.

## Building and selecting the syllabus

[`apps/syllabus.py`](../apps/syllabus.py) builds an outline with a document root and chapter, subtopic, and keyword branches. It uses these sources in order:

1. **Original PDF layout.** Existing bookmarks are matched to text or destination positions. When usable bookmarks are absent, the code infers heading levels from font size, bold text, and heading patterns such as `Chapter`, `Session`, or `Unit`. It preserves same-page boundaries and skips table-of-contents text. The builder matches graph fact names and aliases to normalized text in each heading's page segment and attaches edges whose endpoints both match that segment.
2. **Graph hierarchy.** If the PDF is unavailable or yields no usable outline, `part_of`, `include_in`, and `is_a` reconstruct sections and connect them to fact edges.
3. **Page fallback.** If there are still no branches, the outline groups facts by source page. These branches provide provenance without defining named chapters for cross-topic ranking.

Branches have stable 24-character IDs derived from the parent ID, sibling position, and title for an unchanged outline. The outline API exposes `id`, `title`, `kind`, `children`, and `selectable`. The server and worker resolve choices to `LocatedLink` records carrying the original directed fact triple, one-based source pages, and the named topic path. Only branches with usable evidence are selectable. Choosing a parent includes its descendants. The whole-document scope includes the remaining fact-to-fact edges even if the outline could not assign them a named topic.

In the workspace, **Chapters** shows this hierarchy and **Relationships** shows the full exported graph. Syllabus choices restrict question evidence. Both views use the same saved graph, while the outline supplies the section names and assignment of facts to sections. See [React workspace](frontend.md) for graph labels and fullscreen.
