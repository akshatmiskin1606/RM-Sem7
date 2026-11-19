# React workspace

The workspace is a React single-page interface built by Vite and served by the local Python backend. [`main.jsx`](../web/src/main.jsx) owns application state and API calls, and [`style.css`](../web/src/style.css) includes responsive and reduced-motion styles.

## Workflow and state

1. Choose or drop a PDF and click **Build graph**, or pick an existing graph in **Graph history**. Each upload is stored separately. Selecting a saved graph opens its chapters and any previous question results so you can generate a new batch from the same evidence.
2. Review the graph and optionally select topics in **Chapters**. **Syllabus Control** lists explicit selections. Choose **Clear** to return to whole-document generation.
3. Choose the number of questions and difficulty, then click **Generate questions**. Enable **Apply QUBO optimisation** to make the advanced collection settings available. See [QUBO optimisation](optimisation.md) for the controls and time budget.
4. Open **Questions** to view the questions and answer key. Questions include evidence paths and page references when available. When a candidate pool has been published, the view offers **Final Set** and **Candidate Set** tabs. Each set supports downloads and quiz attempts.

The initial document comes from a valid `?document=<id>` parameter, the last document opened in this browser, or the build-time `VITE_DEFAULT_DOCUMENT`, in that order. Graph history comes from the server's saved run directories and survives browser and server restarts. While a job runs, you can browse other graphs and use **View active job** to go back to its progress and cancellation controls. The server accepts one graph build or question generation job at a time.

The frontend polls approximately once per second during a job and retries a failed document poll after two seconds while the job is active. The **Activity** panel shows progress and exposes **Cancel run**. The [operations guide](operations.md) describes the two more detailed terminal streams.

The `useArtifact()` hook loads data by endpoint and version. For questions and candidates the version is the published filename, so it reloads when the checkpoint or selected result becomes current. It aborts stale fetches on changes. Controls disable during an active job and prevent invalid counts or time budgets from being submitted from the UI.

## Graph views

[`Syllabus.jsx`](../web/src/Syllabus.jsx) recursively renders the document outline. The document starts expanded. Individual chapters and subtopics can be expanded as needed. Selecting a branch includes its descendants and clears redundant explicit child selections. Descendant checkboxes show inherited selection. The branch tree and evidence mapping are described in [knowledge graph and syllabus](knowledge-graph.md).

[`Graph.jsx`](../web/src/Graph.jsx) uses `react-force-graph-2d` to display every saved node and directed relationship. The relationship view loads on demand. Nodes are coloured by label, and parallel links curve apart so individual relationships can be inspected. The canvas places labels in available screen space and shortens long labels. Zooming makes more labels fit. Hovering or selecting an edge shows its full relationship type, and selecting a node shows its full name and source page when known.

**Fit graph** zooms to the graph bounds. **Full screen** uses the browser fullscreen API with an expanded-panel fallback. The renderer resizes and fits the graph as the available space changes. **Download graph** is available from either graph view and offers the saved JSON, GraphML, and a ZIP of the node and relationship CSV files.

## Quiz attempt and downloads

**Start Quiz** copies the displayed set into [`QuizAttempt.jsx`](../web/src/QuizAttempt.jsx). Each question uses a group of four radio inputs and shows progress as the learner answers. **Submit Quiz** scores the selections locally and shows the count correct, rounded percentage, incorrect and unanswered counts, and an answer review. **Retake quiz** resets the attempt. **Back to questions** returns to the results and restores focus to the start button when it is available.

Quiz responses and scores live in component state and end when the user leaves the attempt or reloads. This is a local practice mode. The answer keys are part of the question artifact delivered to the browser.

The **Download** menu links to server-rendered PDF, CSV, and JSON exports for the currently displayed set. The PDF and CSV include answer keys. The JSON retains full question criteria, evaluation, and graph evidence. See [API, storage, and exports](api-and-storage.md) for the formats and URLs.
