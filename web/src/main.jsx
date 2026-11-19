import React, { lazy, Suspense, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { indexTopics, SyllabusControl, SyllabusOutline } from './Syllabus.jsx';
import QuizAttempt, { LETTERS } from './QuizAttempt.jsx';
import './style.css';

const Graph = lazy(() => import('./Graph.jsx'));
const LAST_DOCUMENT = 'kaqg-last-document';
const THEME_PREFERENCE = 'kaqg-theme';
const DOCUMENT_ID = /^[a-f0-9]{32}$/;
const WHOLE_DOCUMENT = [];
const DIFFICULTY = {
  easy: { label: 'Easy', hint: 'Recall one direct relationship.' },
  medium: { label: 'Medium', hint: 'Combine two connected relationships.' },
  hard: { label: 'Hard', hint: 'Combine three relationships, across topics when possible.' },
};
const number = new Intl.NumberFormat();
const savedDate = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'medium' });
const DEFAULT_BALANCE_SETTINGS = { extra_questions: 2, max_seconds: 30 };
const MAX_EXTRA_QUESTIONS = 50;
const MAX_EXTRA_SECONDS = 3600;
const QUESTION_EXPORTS = [ ['pdf', 'PDF', '.pdf'], ['csv', 'CSV', '.csv'], ['json', 'JSON', '.json'] ];
const GRAPH_EXPORTS = [ ['json', 'JSON', '.json'], ['graphml', 'GraphML', '.graphml'], ['csv', 'CSV (ZIP)', '-csv.zip'] ];

function isValidCount(value, maximum) {
  const count = Number(value);
  return Number.isInteger(count) && count >= 1 && count <= maximum;
}

function initialDocument() {
  const requested = new URLSearchParams(window.location.search).get('document');
  let saved = null;
  try { saved = localStorage.getItem(LAST_DOCUMENT); } catch { /* Browser storage may be off. */ }
  return [requested, saved, import.meta.env.VITE_DEFAULT_DOCUMENT]
    .find(id => typeof id === 'string' && DOCUMENT_ID.test(id)) ?? null;
}

async function api(path, options = {}) {
  const response = await fetch(`/api${path}`, options);
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || 'KAQG could not complete the request.');
  return result;
}

function post(path, body, headers = {}) {
  return api(path, { method: 'POST', body, headers: { 'X-KAQG-Request': '1', ...headers } });
}

function useArtifact(path, version) {
  const [result, setResult] = useState(null);
  const [failure, setFailure] = useState(null);
  useEffect(() => {
    if (!path) return;
    const signal = new AbortController();
    api(path, { signal: signal.signal }).then(data => setResult({ path, version, data })).catch(error => {
      if (error.name !== 'AbortError') setFailure({ path, version, message: error.message });
    });
    return () => signal.abort();
  }, [path, version]);
  return {
    data: result && result.path === path && result.version === version ? result.data : null,
    error: failure && failure.path === path && failure.version === version ? failure.message : '',
  };
}

function Brand() {
  return <div className="brand"><span className="brand-icon" aria-hidden="true"><i /><i /><i /><i /></span>Study Grid</div>;
}

function GraphIllustration() {
  return <div className="graph-illustration" aria-hidden="true">
    <span className="graph-link link-one" /><span className="graph-link link-two" />
    <span className="graph-link link-three" /><span className="graph-link link-four" />
    <span className="graph-joint joint-one" /><span className="graph-joint joint-two" />
    <span className="graph-joint joint-three" /><span className="graph-joint joint-four" />
    <span className="graph-joint joint-center" />
  </div>;
}

function BlankState({ tab = 'graph', title, message, working = false }) {
  return <div className={`blank-state ${tab === 'graph' ? 'graph-surface' : ''}`}>
    {working ? <span className="spinner" aria-hidden="true" /> : tab === 'graph' ? <GraphIllustration /> : <span className="quiz-icon" aria-hidden="true">?</span>}
    <h2>{title}</h2>
    {message && <p>{message}</p>}
  </div>;
}

function Upload({ file, previousName, busy, onFile }) {
  const input = useRef(null);
  const [dragging, setDragging] = useState(false);
  return <>
    <input ref={input} type="file" accept="application/pdf,.pdf" className="hidden-file" aria-label="Source PDF"
      onChange={event => { onFile(event.target.files[0]); event.target.value = ''; }} disabled={busy} />
    <button className={`drop-zone ${dragging ? 'dragging' : ''}`} type="button" disabled={busy} onClick={() => input.current.click()}
      onDragOver={event => { event.preventDefault(); if (!busy) setDragging(true); }}
      onDragLeave={() => setDragging(false)}
      onDrop={event => { event.preventDefault(); setDragging(false); if (!busy) onFile(event.dataTransfer.files[0]); }}>
      <span className="upload-icon" aria-hidden="true"><i /></span>
      <strong title={file?.name || previousName}>{file?.name || previousName || 'Choose a PDF'}</strong>
      <span>{file ? `${number.format(Math.max(1, Math.round(file.size / 1024)))} KB · Click to change`
        : previousName ? 'Click to choose another PDF' : 'or drag and drop it here'}</span>
    </button>
  </>;
}

function Activity({ job, onCancel, cancelling }) {
  const log = useRef(null);
  const latest = job?.activity.at(-1);
  useEffect(() => {
    if (log.current && job?.status === 'running') log.current.scrollTop = log.current.scrollHeight;
  }, [latest, job?.status]);
  if (!job) return null;
  const labels = { running: 'In progress', complete: 'Complete', partial: 'Partial result', cancelled: 'Cancelled', failed: 'Failed' };
  return <details className="panel activity" open>
    <summary><span>Activity</span><span className={`status ${job.status}`}><i />{cancelling ? 'Stopping' : labels[job.status]}</span></summary>
    <div className="activity-body">
      {job.activity.length ? <ol className="activity-list" aria-label="Pipeline steps" ref={log}>
        {job.activity.map((message, i) => <li key={`${i}:${message}`}>{message}</li>)}
      </ol> : <p className="activity-start">Starting KAQG…</p>}
      {job.error && <p className="inline-error" role="alert">{job.error}</p>}
      {job.status === 'running' && <button className="text-button cancel" onClick={onCancel} disabled={cancelling}>Cancel run</button>}
    </div>
  </details>;
}

function GraphEvidence({ reasoning }) {
  const topics = new Set(reasoning.links.filter(link => link.topic.length).map(link => JSON.stringify(link.topic)));
  return <details className="question-evidence">
    <summary>Graph evidence · {reasoning.nodes.length} nodes · {reasoning.links.length} {reasoning.links.length === 1 ? 'link' : 'links'}
      {topics.size > 1 && ` · ${topics.size} topics`}</summary>
    <ul>{reasoning.links.map((link, index) => <li key={index}>
      <span>{link.source} → <strong>{link.relation}</strong> → {link.target}</span>
      {(link.topic.length > 0 || link.pages.length > 0) && <small>
        {[link.topic.join(' / '), link.pages.length && `${link.pages.length === 1 ? 'Page' : 'Pages'} ${link.pages.join(', ')}`].filter(Boolean).join(' · ')}
      </small>}
    </li>)}</ul>
  </details>;
}

function DownloadMenu({ url, fileName, label, formats, className, title = 'Download' }) {
  return <details className={`download-menu ${className}`} key={url} onKeyDown={event => {
    if (event.key === 'Escape') {
      event.currentTarget.open = false;
      event.currentTarget.querySelector('summary').focus();
    }
  }}>
    <summary className="small-button" aria-label={label || title}>{title}</summary>
    <ul>{formats.map(([format, option, suffix]) => <li key={format}>
      <a href={`${url}?format=${format}`} download={`${fileName}${suffix}`} onClick={event => {
        const menu = event.currentTarget.closest('details');
        menu.open = false;
        menu.querySelector('summary').focus();
      }}>{option}</a>
    </li>)}</ul>
  </details>;
}

function QuestionResults({ result, target, url, candidateSet = false, onStartQuiz, startQuizButton }) {
  return <>
    <div className="result-meta">
      <span><strong>{result.assessments.length}</strong> of {target} {candidateSet ? 'candidates' : 'questions'}{DIFFICULTY[result.difficulty] && ` · ${DIFFICULTY[result.difficulty].label}`}</span>
      <div className="question-actions">
        <DownloadMenu url={url} fileName={candidateSet ? 'candidates' : 'questions'} formats={QUESTION_EXPORTS}
          label={candidateSet ? 'Download candidate set' : 'Download questions'} className="quiz-download" />
        <button type="button" className="small-button primary" ref={startQuizButton} disabled={!result.assessments.length}
          onClick={() => onStartQuiz(result, candidateSet)}>Start Quiz</button>
      </div>
    </div>
    <ol className="quiz-list">
      {result.assessments.map(({ question, question_criteria: criteria }, index) => <li className="question" key={`${index}:${question.stem}`}>
        <strong>{question.stem}</strong>
        {criteria?.syllabus_topic && <p className="question-source">{criteria.syllabus_topic}{criteria.source_page && ` · Page ${criteria.source_page}`}</p>}
        <ol type="A">{LETTERS.map(letter => <li key={letter}>{question[`option_${letter}`]}</li>)}</ol>
        {criteria?.graph_reasoning && <GraphEvidence reasoning={criteria.graph_reasoning} />}
      </li>)}
    </ol>
    <details className="answer-key"><summary>Answer key</summary><ol>
      {result.assessments.map(({ question }, index) => <li key={index}><strong>{question.answer}.</strong> {question[`option_${question.answer}`]}</li>)}
    </ol></details>
  </>;
}

function App() {
  const [theme, setTheme] = useState(() => document.documentElement.dataset.theme === 'light' ? 'light' : 'dark');
  const [id, setId] = useState(initialDocument);
  const [documentStatus, setDocumentStatus] = useState(null);
  const [workspace, setWorkspace] = useState(null);
  const [historyError, setHistoryError] = useState('');
  const [historyRetry, setHistoryRetry] = useState(0);
  const [file, setFile] = useState(null);
  const [count, setCount] = useState('10');
  const [balance, setBalance] = useState(false);
  const [balanceDraft, setBalanceDraft] = useState(null);
  const [questionSet, setQuestionSet] = useState('final');
  const [quizAttempt, setQuizAttempt] = useState(null);
  const startQuizButton = useRef(null);
  const [difficultyChoice, setDifficultyChoice] = useState(null);
  const [tab, setTab] = useState('graph');
  const [graphView, setGraphView] = useState('chapters');
  const [syllabusSelection, setSyllabusSelection] = useState(null);
  const [pending, setPending] = useState('');
  const [cancelling, setCancelling] = useState(false);
  const [error, setError] = useState('');
  const [connectionIssue, setConnectionIssue] = useState('');
  const documentPath = id ? `/documents/${id}` : null;
  const current = documentStatus?.id === id ? documentStatus : null;
  const job = current?.job;
  const balanceSettings = balanceDraft ?? job?.balance_settings ?? DEFAULT_BALANCE_SETTINGS;
  const validExtras = isValidCount(balanceSettings.extra_questions, MAX_EXTRA_QUESTIONS);
  const validWindow = isValidCount(balanceSettings.max_seconds, MAX_EXTRA_SECONDS);
  const difficulty = difficultyChoice ?? job?.difficulty ?? 'medium';
  const running = job?.status === 'running';
  const active = workspace?.active;
  const otherJob = active && active.id !== id ? active : null;
  const opening = Boolean(documentPath && !current && !connectionIssue);
  const busy = running || opening || Boolean(pending || active);
  const savedGraphs = workspace?.documents ?? [];
  const selectedGraph = savedGraphs.find(entry => entry.id === id);
  const graphPath = current?.graph && `${documentPath}/graph`;
  const syllabusPath = current?.graph && `${documentPath}/syllabus`;
  const questionPath = current?.questions && `${documentPath}/questions`;
  const candidatePool = current?.questions?.candidates;
  const candidatePath = candidatePool && `${documentPath}/candidates`;
  const graph = useArtifact(graphView === 'relationships' ? graphPath : null, id);
  const syllabus = useArtifact(syllabusPath, id);
  const quiz = useArtifact(questionPath, current?.questions?.file);
  const candidates = useArtifact(questionSet === 'candidates' ? candidatePath : null, candidatePool?.file);
  const topics = useMemo(() => indexTopics(syllabus.data), [syllabus.data]);
  const selectedTopics = syllabusSelection?.id === id ? syllabusSelection.topics : job?.syllabus ?? WHOLE_DOCUMENT;
  const selectedTopicSet = useMemo(() => new Set(selectedTopics), [selectedTopics]);
  const previousTopics = current?.questions?.syllabus ?? WHOLE_DOCUMENT;
  const canContinue = current?.questions?.target === Number(count) && current.questions.count < Number(count)
    && current.questions.difficulty === difficulty && current.questions.graph_reasoning === true
    && previousTopics.length === selectedTopics.length && previousTopics.every(topic => selectedTopicSet.has(topic));
  const questionTitle = canContinue ? `Continue to ${count} questions` : 'Generate questions';

  function startQuiz(result, candidateSet) {
    setQuizAttempt({
      setName: candidateSet ? 'Candidate Set' : 'Final Set',
      questions: result.assessments.map(({ question }) => ({ ...question, answer: String(question.answer ?? '').trim().toUpperCase() })),
    });
  }

  function exitQuiz() {
    setQuizAttempt(null);
    requestAnimationFrame(() => startQuizButton.current?.focus());
  }

  useLayoutEffect(() => {
    const root = document.documentElement;
    root.dataset.theme = theme;
    document.querySelector('meta[name="theme-color"]').content = getComputedStyle(root).getPropertyValue('--page').trim();
  }, [theme]);

  function toggleTheme() {
    const nextTheme = theme === 'dark' ? 'light' : 'dark';
    setTheme(nextTheme);
    try { localStorage.setItem(THEME_PREFERENCE, nextTheme); } catch { /* Browser storage may be off. */ }
  }

  useEffect(() => {
    if (!documentPath || pending || (current && !running)) return;
    const controller = new AbortController();
    let nextCheck;
    async function refresh() {
      try {
        const data = await api(documentPath, { signal: controller.signal });
        if (controller.signal.aborted) return;
        setDocumentStatus(data);
        setConnectionIssue('');
        if (data.job.status === 'running') nextCheck = setTimeout(refresh, 1000);
        else setCancelling(false);
      } catch (problem) {
        if (controller.signal.aborted) return;
        setConnectionIssue(problem.message);
        if (running) nextCheck = setTimeout(refresh, 2000);
      }
    }
    void refresh();
    return () => { controller.abort(); clearTimeout(nextCheck); };
  }, [documentPath, Boolean(current), running, pending]);

  useEffect(() => {
    const controller = new AbortController();
    let nextCheck;
    let checking = false;
    async function refreshHistory() {
      if (checking) return;
      clearTimeout(nextCheck);
      checking = true;
      try {
        const data = await api('/documents', { signal: controller.signal });
        if (controller.signal.aborted) return;
        setWorkspace(data);
        setHistoryError('');
        if (data.active) nextCheck = setTimeout(refreshHistory, 1000);
      } catch (problem) {
        if (controller.signal.aborted) return;
        setHistoryError(problem.message);
        nextCheck = setTimeout(refreshHistory, 3000);
      } finally {
        checking = false;
      }
    }
    void refreshHistory();
    window.addEventListener('focus', refreshHistory);
    return () => {
      controller.abort();
      clearTimeout(nextCheck);
      window.removeEventListener('focus', refreshHistory);
    };
  }, [running, pending, historyRetry]);

  function openDocument(identity, status = null) {
    setId(identity);
    setDocumentStatus(status);
    setGraphView('chapters');
    setTab('graph');
    setQuestionSet('final');
    setSyllabusSelection(null);
    setDifficultyChoice(null);
    setBalanceDraft(null);
    setConnectionIssue('');
    setError('');
    const url = new URL(window.location.href);
    url.searchParams.set('document', identity);
    window.history.replaceState(null, '', url);
    try { localStorage.setItem(LAST_DOCUMENT, identity); } catch { /* Browser storage may be off. */ }
  }

  function selectFile(chosen) {
    if (!chosen) return;
    if (!/\.pdf$/i.test(chosen.name) || chosen.size > 100 * 1024 * 1024) {
      setError('Choose a PDF up to 100 MB.');
      return;
    }
    setFile(chosen);
    setError('');
  }

  function toggleTopic(topic) {
    const next = new Set(selectedTopics);
    if (!next.delete(topic.id)) {
      for (const branchId of indexTopics(topic).keys()) next.delete(branchId);
      next.add(topic.id);
    }
    setSyllabusSelection({ id, topics: [...next] });
  }

  async function start(stage) {
    setPending(stage);
    setError('');
    setConnectionIssue('');
    setTab(stage);
    if (stage === 'questions') setQuestionSet('final');
    try {
      const data = stage === 'graph'
        ? await post('/documents', file, { 'Content-Type': 'application/pdf', 'X-PDF-Name': encodeURIComponent(file.name) })
        : await post(`${documentPath}/questions`, JSON.stringify({
          count: Number(count), syllabus: selectedTopics, difficulty, balance,
          ...(balance && { balance_settings: { extra_questions: Number(balanceSettings.extra_questions), max_seconds: Number(balanceSettings.max_seconds) } }),
        }), { 'Content-Type': 'application/json' });
      if (stage === 'graph') {
        setFile(null);
        openDocument(data.id, data);
      } else {
        setDocumentStatus(data);
      }
    } catch (problem) {
      setError(problem.message);
    } finally {
      setPending('');
    }
  }

  async function cancel() {
    setCancelling(true);
    setError('');
    try {
      await post(`${documentPath}/cancel`);
    } catch (problem) {
      setError(problem.message);
      setCancelling(false);
    }
  }

  const statusMessage = job?.activity.at(-1);
  const building = pending === 'graph' || (running && job?.stage === 'graph');
  const generating = pending === 'questions' || (running && job?.stage === 'questions');
  const balancing = running && job?.phase === 'balancing';

  return <>
    <header className="topbar"><div className="frame topbar-inner">
      <Brand />
      <div className="topbar-actions">
        <span className="local"><i />Local workspace</span>
        <button type="button" className="theme-toggle small-button" role="switch" aria-checked={theme === 'dark'} onClick={toggleTheme}>
          Dark mode <span className="theme-toggle-indicator" aria-hidden="true" />
        </button>
      </div>
    </div></header>
    {quizAttempt ? <QuizAttempt {...quizAttempt} onExit={exitQuiz} /> : <main className="frame workspace">
      <div className="intro"><h1>PDF to questions</h1><p>Build a knowledge graph from a PDF and turn it into a multiple-choice quiz.</p></div>
      <div className="workspace-grid">
        <aside className="panel controls" aria-label="Generation controls">
          <section className="control-section">
            <h2>Source PDF</h2>
            <Upload file={file} previousName={current?.filename} busy={busy} onFile={selectFile} />
            <button className="primary action" onClick={() => start('graph')} disabled={!file || busy}>{building ? 'Building graph…' : 'Build graph'}<span aria-hidden="true">→</span></button>
          </section>
          <section className="control-section following-section">
            <h2><label htmlFor="graph-history">Graph history</label></h2>
            <select id="graph-history" className="graph-history-select" value={selectedGraph?.id ?? ''}
              title={selectedGraph?.filename} disabled={!savedGraphs.length || Boolean(pending) || cancelling}
              onChange={event => openDocument(event.target.value)}>
              <option value="" disabled>{workspace && !savedGraphs.length ? 'No saved graphs yet' : 'Choose a saved graph'}</option>
              {savedGraphs.map(entry => <option key={entry.id} value={entry.id}>
                {entry.filename} — {savedDate.format(entry.saved_at * 1000)}
              </option>)}
            </select>
            {historyError && <p className="control-note inline-error" role="alert">Could not load graph history.{' '}
              <button type="button" className="text-button" onClick={() => setHistoryRetry(value => value + 1)}>Retry</button>
            </p>}
            {otherJob && <div className="control-note history-job">
              <p role="status">{otherJob.stage === 'graph' ? 'Building graph for ' : 'Generating questions for '}{otherJob.filename}</p>
              <button type="button" className="text-button" disabled={Boolean(pending) || cancelling}
                onClick={() => openDocument(otherJob.id)}>View active job</button>
            </div>}
          </section>
          <section className="control-section following-section">
            <h2>Question batch</h2>
            {current?.graph && <SyllabusControl selected={selectedTopics} topics={topics} disabled={busy}
              onClear={() => setSyllabusSelection({ id, topics: [] })} />}
            <label className="count-field" htmlFor="count">Number of questions
              <input id="count" type="number" inputMode="numeric" min="1" max="50" value={count} disabled={busy} onChange={event => setCount(event.target.value)} />
            </label>
            <label className="count-field difficulty-field" htmlFor="difficulty">Difficulty
              <select id="difficulty" value={difficulty} disabled={busy} aria-describedby="difficulty-help" onChange={event => setDifficultyChoice(event.target.value)}>
                {Object.entries(DIFFICULTY).map(([value, { label }]) => <option key={value} value={value}>{label}</option>)}
              </select>
            </label>
            <p className="control-note" id="difficulty-help">{DIFFICULTY[difficulty].hint}</p>
            <label className="balance-field">
              <input type="checkbox" checked={balance} disabled={busy} aria-describedby="balance-help" onChange={event => setBalance(event.target.checked)} />
              <span>Apply QUBO optimisation</span>
            </label>
            <p className="control-note" id="balance-help">Save your quiz first, then look for extra candidates and use a classical solver to improve topic coverage.</p>
            {balance && <details className="balance-settings">
              <summary>Advanced settings</summary>
              <label className="count-field" htmlFor="balance-extras">Extra questions
                <input id="balance-extras" type="number" inputMode="numeric" min="1" max={MAX_EXTRA_QUESTIONS}
                  value={balanceSettings.extra_questions} disabled={busy} aria-invalid={!validExtras}
                  onChange={event => setBalanceDraft({ ...balanceSettings, extra_questions: event.target.value })} />
              </label>
              <label className="count-field" htmlFor="balance-seconds">Max extra time (seconds)
                <input id="balance-seconds" type="number" inputMode="numeric" min="1" max={MAX_EXTRA_SECONDS}
                  value={balanceSettings.max_seconds} disabled={busy} aria-invalid={!validWindow}
                  onChange={event => setBalanceDraft({ ...balanceSettings, max_seconds: event.target.value })} />
              </label>
              <p className="control-note">Extra generation stops at either limit. More candidates give the selector more choices and can take longer.</p>
            </details>}
            {balance && !validExtras && <p className="control-note inline-error" role="alert">Enter 1–{MAX_EXTRA_QUESTIONS} extra questions.</p>}
            {balance && !validWindow && <p className="control-note inline-error" role="alert">Enter 1–{MAX_EXTRA_SECONDS} seconds.</p>}
            <button className={`action ${current?.graph ? 'primary' : 'secondary'}`} onClick={() => start('questions')}
              disabled={!current?.graph || busy || !isValidCount(count, 50) || (balance && (!validExtras || !validWindow))}>
              {generating ? 'Generating questions…' : questionTitle}<span aria-hidden="true">→</span>
            </button>
            <p className="control-note">{current?.graph ? 'Uses the saved graph for this PDF.' : 'Available once your graph is ready.'}</p>
          </section>
          {(error || connectionIssue) && <p className="inline-error control-error" role="alert">{error || connectionIssue}</p>}
        </aside>
        <div className="output-column">
          <section className="panel output" aria-label="Results">
            <nav className="tabs" aria-label="Results views">
              <button className={tab === 'graph' ? 'active' : ''} aria-pressed={tab === 'graph'} onClick={() => setTab('graph')}>Knowledge graph</button>
              <button className={tab === 'questions' ? 'active' : ''} aria-pressed={tab === 'questions'} onClick={() => setTab('questions')}>Questions{current?.questions && <span className="tab-count">{current.questions.count}</span>}</button>
            </nav>
            {tab === 'graph' ? (
              building ? <BlankState title="Building your graph" message={statusMessage || 'Uploading the PDF…'} working />
                : opening ? <BlankState title="Opening your graph…" working />
                : current?.graph ? <>
                  <div className="result-meta">
                    <span><strong>{number.format(current.graph.nodes)}</strong> nodes <i /> <strong>{number.format(current.graph.relationships)}</strong> relationships <i /> {current.graph.pages} {current.graph.pages === 1 ? 'page' : 'pages'}</span>
                    <DownloadMenu url={`/api${graphPath}`} fileName="knowledge-graph" title="Download graph"
                      formats={GRAPH_EXPORTS} className="graph-download" />
                  </div>
                  <div className="graph-view-switch" role="group" aria-label="Graph view">
                    <button type="button" className="small-button" aria-pressed={graphView === 'chapters'} onClick={() => setGraphView('chapters')}>Chapters</button>
                    <button type="button" className="small-button" aria-pressed={graphView === 'relationships'} onClick={() => setGraphView('relationships')}>Relationships</button>
                  </div>
                  {graphView === 'chapters'
                    ? syllabus.data ? <SyllabusOutline key={id} root={syllabus.data} selected={selectedTopicSet} disabled={busy} onToggle={toggleTopic} />
                      : <BlankState title={syllabus.error || 'Opening chapters…'} working={!syllabus.error} />
                    : graph.data ? <Suspense fallback={<BlankState title="Opening graph…" working />}><Graph key={id} result={graph.data} theme={theme} /></Suspense>
                      : <BlankState title={graph.error || 'Opening graph…'} working={!graph.error} />}
                </> : <BlankState title={job?.status === 'failed' ? 'Graph could not be built' : 'No graph yet'} message={job?.status === 'failed' ? 'Check the activity log and try the PDF again.' : 'Upload a PDF to build your knowledge graph.'} />
            ) : (
              quiz.data && (!generating || balancing) ? <>
                {balancing && <p className="balance-progress" role="status">Quiz saved. Checking extra candidates…</p>}
                {candidatePool && <div className="graph-view-switch" role="group" aria-label="Question sets">
                  <button type="button" className="small-button" aria-pressed={questionSet === 'final'} onClick={() => setQuestionSet('final')}>Final Set</button>
                  <button type="button" className="small-button" aria-pressed={questionSet === 'candidates'} onClick={() => setQuestionSet('candidates')}>Candidate Set ({candidatePool.count})</button>
                </div>}
                {candidatePool && questionSet === 'candidates'
                  ? candidates.data ? <QuestionResults result={candidates.data} target={candidatePool.target} url={`/api${candidatePath}`} candidateSet
                    onStartQuiz={startQuiz} startQuizButton={startQuizButton} />
                    : <BlankState tab="questions" title={candidates.error || 'Opening candidate set…'} working={!candidates.error} />
                  : <QuestionResults result={quiz.data} target={current.questions.target} url={`/api${questionPath}`}
                    onStartQuiz={startQuiz} startQuizButton={startQuizButton} />}
              </>
                : <BlankState tab="questions" title={generating ? 'Generating your questions' : quiz.error || 'No questions yet'}
                  message={generating ? statusMessage || 'Opening the saved graph…' : current?.graph ? 'Generate a batch from your saved graph.' : 'Build a knowledge graph to get started.'} working={generating} />
            )}
          </section>
          <Activity job={job} onCancel={cancel} cancelling={cancelling} />
        </div>
      </div>
    </main>}
  </>;
}

createRoot(document.getElementById('root')).render(<App />);
