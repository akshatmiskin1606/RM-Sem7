# KAQG implementation documentation

These documents describe the Fedora workspace in this checkout, from PDF ingestion to an exported or interactive multiple-choice quiz. They also identify where the workspace uses the original KAQG services and where it runs the same generation and evaluation classes directly.

| Document | Covers |
| --- | --- |
| [System architecture](architecture.md) | Components, process boundaries, data flow, and differences among ingestion and generation modes |
| [Knowledge graph and syllabus](knowledge-graph.md) | PDF extraction, Neo4j schema, graph JSON, chapter reconstruction, and scope resolution |
| [Question generation and difficulty](question-generation.md) | Evidence paths, KAQG feature scoring, answer verification, retries, and saved assessments |
| [QUBO optimisation](optimisation.md) | Candidate collection, checkpoint and deadline, objective function, and exact and bounded solvers |
| [React workspace](frontend.md) | Page state, graph views, generation controls, quiz attempts, and download controls |
| [API, storage, and exports](api-and-storage.md) | HTTP contracts, job state, saved files, and JSON, CSV, and PDF formats |
| [Local operations and testing](operations.md) | Fedora setup, commands, log windows, failure recovery, and verification |

For a demo, start with [local operations](operations.md), then follow the [React workspace](frontend.md) from graph build to quiz. For the technical discussion, use the [architecture](architecture.md) and the connected evidence and selection descriptions in [question generation](question-generation.md) and [optimisation](optimisation.md).
