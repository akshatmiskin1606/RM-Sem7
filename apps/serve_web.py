"""Serve the React KAQG workspace and run the existing local PDF pipeline."""

import argparse
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
from threading import Event, RLock, Thread
import time
import traceback
from urllib.parse import parse_qs, unquote, urlsplit
from uuid import uuid4

from assessment_selector import BalanceSettings, CHECKPOINT_MESSAGE, select_questions
from graph_exports import GRAPH_DOWNLOADS, csv_archive, graphml
from pdf_to_mcq import DIFFICULTIES, ROOT, RUNTIME, read_saved_graph
from question_exports import CONTENT_TYPES, questions_csv, questions_pdf
from syllabus import build_syllabus, resolve_topics


BUILD = ROOT / 'web' / 'dist'
MAX_PDF_BYTES = 100 * 1024 * 1024
DOCUMENT_ID = re.compile(r'[a-f0-9]{32}')
PROGRESS = re.compile(r'^\[\d\d:\d\d:\d\d\] (.+)$')


class RequestError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


@dataclass
class Job:
    document: Path
    state: dict
    stopped: Event = field(default_factory=Event)
    activity: list[str] = field(default_factory=list)
    process: subprocess.Popen | None = None
    thread: Thread | None = None
    last_error: str = ''


class Workspace:
    def __init__(self, directory):
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.lock = RLock()
        self.active = None
        self.closing = False

    def _load(self, document):
        try:
            return json.loads((document / 'state.json').read_text(encoding='utf-8'))
        except FileNotFoundError:
            raise RequestError(HTTPStatus.NOT_FOUND, 'This PDF run could not be found.') from None

    def _save(self, job):
        job.state['job']['activity'] = list(job.activity)
        file = job.document / 'state.tmp'
        file.write_text(json.dumps(job.state, ensure_ascii=False), encoding='utf-8')
        file.replace(job.document / 'state.json')

    def _state(self, document):
        if self.active and self.active.document == document:
            return self.active.state
        state = self._load(document)
        if state['job']['status'] == 'running':
            state['job'].update(status='cancelled', error='The previous server session ended during this run.')
        return state

    def status(self, identity):
        with self.lock:
            state = self._state(self.directory / identity)
            if self.active and self.active.document.name == identity:
                state = {**state, 'job': {**state['job'], 'activity': list(self.active.activity)}}
            return state

    def _require_idle(self):
        if self.active or self.closing:
            raise RequestError(HTTPStatus.CONFLICT, 'KAQG is already running a job. Wait for it to finish or cancel it.')

    def upload(self, filename, data):
        with self.lock:
            self._require_idle()
            document = self.directory / uuid4().hex
            document.mkdir(mode=0o700)
            (document / filename).write_bytes(data)
            state = {'id': document.name, 'filename': filename, 'graph': None, 'questions': None}
            return self._start(document, state, 'graph', self._build_graph)

    @lru_cache(maxsize=8)
    def _syllabus(self, document, filename):
        graph = read_saved_graph(document / 'knowledge-graph.json')
        pdf = document / filename
        return build_syllabus(graph, pdf if pdf.is_file() else None)

    def syllabus(self, identity):
        with self.lock:
            document = self.directory / identity
            state = self._state(document)
            if not state['graph']:
                raise RequestError(HTTPStatus.NOT_FOUND, 'Build the graph to open its syllabus.')
            outline, _ = self._syllabus(document, state['filename'])
            return outline

    def generate(self, identity, target, syllabus=(), difficulty='medium', balance_settings=None):
        with self.lock:
            self._require_idle()
            document = self.directory / identity
            state = self._state(document)
            if not state['graph']:
                raise RequestError(HTTPStatus.CONFLICT, 'Build the knowledge graph before generating questions.')
            if not isinstance(difficulty, str) or difficulty not in DIFFICULTIES:
                raise RequestError(HTTPStatus.BAD_REQUEST, 'Choose Easy, Medium, or Hard.')
            if syllabus:
                _, scopes = self._syllabus(document, state['filename'])
                try:
                    resolve_topics(scopes, syllabus)
                except ValueError as error:
                    raise RequestError(HTTPStatus.BAD_REQUEST, str(error)) from error
            return self._start(document, state, 'questions', self._generate_questions, target, syllabus, difficulty, balance_settings)

    def artifact(self, identity, artifact):
        with self.lock:
            document = self.directory / identity
            state = self._state(document)
            if artifact == 'graph' and state['graph']:
                return document / 'knowledge-graph.json'
            questions = state.get('questions') or {}
            entry = {'questions': questions, 'candidates': questions.get('candidates')}.get(artifact)
            if not entry:
                raise RequestError(HTTPStatus.NOT_FOUND, 'This result is not ready yet.')
            return document / entry['file']

    def question_download(self, identity, artifact, export_format):
        data = self.artifact(identity, artifact).read_bytes()
        if export_format == 'json':
            return data
        result = json.loads(data)
        if export_format == 'csv':
            return questions_csv(result)
        # Serialize PyMuPDF calls with syllabus parsing in this threaded server.
        with self.lock:
            return questions_pdf(result, candidate_set=artifact == 'candidates')

    def graph_download(self, identity, export_format):
        data = self.artifact(identity, 'graph').read_bytes()
        if export_format == 'json':
            return data
        graph = json.loads(data)
        return graphml(graph) if export_format == 'graphml' else csv_archive(graph)

    def _start(self, document, state, stage, routine, *args):
        state['job'] = {'stage': stage, 'status': 'running', 'error': '', 'target': args[0] if args else None}
        if stage == 'questions':
            settings = args[3]
            state['job'].update(syllabus=args[1], difficulty=args[2], balance=settings is not None)
            if settings:
                state['job']['balance_settings'] = asdict(settings)
        job = Job(document, state)
        self._save(job)
        self.active = job
        job.thread = Thread(target=self._work, args=(job, routine, args), name=f'kaqg-{stage}')
        job.thread.start()
        return self.status(document.name)

    def _work(self, job, routine, args):
        status, error = 'complete', ''
        self._log(job, f"Started {job.state['job']['stage']} job for {job.state['filename']}.")
        try:
            status = routine(job, *args)
        except Exception as problem:
            status, error = 'failed', job.last_error or str(problem)
            traceback.print_exc()
        finally:
            with self.lock:
                if job.stopped.is_set():
                    status, error = 'cancelled', ''
                self._log(job, f"{job.state['job']['stage'].capitalize()} job finished with status {status}.")
                job.state['job'].update(status=status, error=error)
                try:
                    self._save(job)
                finally:
                    self.active = None

    def _log(self, job, message, *, relay=True):
        with self.lock:
            if message != (job.activity[-1] if job.activity else None):
                job.activity.append(message)
                if relay:
                    print(f'[KAQG {job.document.name}] {message}', file=sys.stderr, flush=True)

    def _run(self, job, *args, on_checkpoint=None):
        with self.lock:
            if job.stopped.is_set():
                return 130
            job.last_error = ''
            process = subprocess.Popen(
                [sys.executable, '-u', str(ROOT / 'apps' / 'pdf_to_mcq.py'), '--provider', 'local', '--progress', *map(str, args)],
                cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors='replace',
                start_new_session=True,
            )
            job.process = process
        try:
            with process.stdout as output:
                for line in output:
                    print(line, end='', file=sys.stderr, flush=True)
                    message = line.strip()
                    progress = PROGRESS.fullmatch(message)
                    if progress or message.startswith(('Generating question ', 'Loading the saved graph', 'KAQG generated ')):
                        self._log(job, progress[1] if progress else message, relay=False)
                        if on_checkpoint and progress and progress[1] == CHECKPOINT_MESSAGE:
                            on_checkpoint()
                    elif message.startswith('KAQG run failed:'):
                        job.last_error = message
            return process.wait()
        finally:
            with self.lock:
                job.process = None

    def _build_graph(self, job):
        graph_file = job.document / 'knowledge-graph.json'
        code = self._run(job, job.document / job.state['filename'], '--graph-only', '--graph-output', graph_file,
                         '--output', job.document / 'graph-summary.json')
        if code:
            raise RuntimeError('KAQG could not finish building this graph.')
        graph = read_saved_graph(graph_file)
        with self.lock:
            job.state['graph'] = {
                'nodes': len(graph['nodes']), 'relationships': len(graph['relationships']), 'pages': graph['processed_pages'],
            }
        self._log(job, 'Knowledge graph ready.')
        return 'complete'

    def _generate_questions(self, job, target, syllabus, difficulty, balance_settings):
        previous = job.state['questions']
        resume = (previous if previous and previous['target'] == target and previous['count'] < target
                  and previous.get('syllabus', []) == list(syllabus) and previous.get('difficulty') == difficulty
                  and previous.get('graph_reasoning') is True else None)
        scope = [value for topic in syllabus for value in ('--syllabus-topic', topic)]
        pdf = job.document / job.state['filename']
        if pdf.is_file():
            scope.extend(('--syllabus-pdf', pdf))

        def publish(filename, count, candidates=None, balancing=False):
            entry = {'file': filename, 'count': count, 'target': target, 'syllabus': list(syllabus),
                     'difficulty': difficulty, 'graph_reasoning': True}
            if candidates is not None:
                entry['candidates'] = candidates
            with self.lock:
                job.state['questions'] = entry
                if balancing:
                    job.state['job']['phase'] = 'balancing'
                self._save(job)
            return entry

        checkpoint = None
        balance_args = []
        if balance_settings:
            checkpoint = job.document / f'quiz-checkpoint-{uuid4().hex}.json'
            balance_args = ['--balance-checkpoint', checkpoint, '--balance-extra-questions', balance_settings.extra_questions,
                            '--balance-max-seconds', balance_settings.max_seconds]

        def publish_checkpoint():
            # The worker atomically creates this file only after accepting the requested quiz.
            publish(checkpoint.name, target, balancing=True)

        for batch in range(2):
            prefix = 'candidates' if balance_settings else 'questions'
            filename = f'{prefix}-{uuid4().hex}.json'
            destination = job.document / filename
            continuation = ['--resume-questions', job.document / resume['file']] if resume else []
            command = ['--from-graph', job.document / 'knowledge-graph.json', '--questions', target,
                       '--output', destination, '--difficulty', difficulty, '--graph-reasoning', *scope, *continuation, *balance_args]
            code = self._run(job, *command, on_checkpoint=publish_checkpoint) if checkpoint else self._run(job, *command)
            if checkpoint and checkpoint.is_file() and (job.stopped.is_set() or code != 0 or not destination.is_file()):
                publish(checkpoint.name, target)
                self._log(job, 'The saved quiz is available. Optional balancing ended early.')
                return 'complete'
            if job.stopped.is_set():
                return 'cancelled'
            if code not in (0, 1) or not destination.exists():
                if batch and resume:
                    self._log(job, 'The follow-up batch stopped. The accepted questions are available below.')
                    return 'partial'
                raise RuntimeError('KAQG could not verify a question in this run.')
            result = json.loads(destination.read_text(encoding='utf-8'))
            count = len(result['assessments'])
            if balance_settings and count >= target:
                self._log(job, f'Balancing {target} questions from {count} validated candidates.')
                selected, details = select_questions(result['assessments'], target)
                final_name = f'questions-{uuid4().hex}.json'
                with (job.document / final_name).open('x', encoding='utf-8') as out:
                    json.dump({**result, 'assessments': selected, 'selection': details}, out, ensure_ascii=False, indent=2)
                publish(final_name, target, candidates={'file': filename, 'count': count,
                                                        'target': target + balance_settings.extra_questions})
                self._log(job, f'Final set ready. Selected {target} of {count} candidates.')
                return 'complete'
            resume = publish(filename, count)
            if count == target:
                return 'complete'
            if not batch:
                self._log(job, f'Kept {count} accepted questions. Continuing toward {target}.')
        return 'partial'

    def cancel(self, identity):
        with self.lock:
            job = self.active
            if not job or job.document.name != identity:
                raise RequestError(HTTPStatus.CONFLICT, 'This PDF has no active job.')
            if not job.stopped.is_set():
                job.stopped.set()
                self._log(job, 'Stopping the KAQG workers and temporary services…')
                if job.process and job.process.poll() is None:
                    job.process.terminate()
            return self.status(identity)

    def close(self):
        with self.lock:
            self.closing = True
            job = self.active
            if job:
                self.cancel(job.document.name)
        if job:
            job.thread.join()


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=BUILD, **kwargs)

    def _check_host(self):
        port = self.server.server_port
        if self.headers.get('Host') not in {f'127.0.0.1:{port}', f'localhost:{port}'}:
            raise RequestError(HTTPStatus.FORBIDDEN, 'Open the KAQG workspace on localhost.')

    def _respond(self, body, content_type='application/json', status=HTTPStatus.OK, filename=None):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        if filename:
            self.send_header('Content-Disposition', f'attachment; filename="{filename}"')
        self.end_headers()
        self.wfile.write(body)

    def _json(self, data, status=HTTPStatus.OK):
        self._respond(json.dumps(data, ensure_ascii=False).encode('utf-8'), status=status)

    def _body(self, limit):
        try:
            size = int(self.headers.get('Content-Length', '0'))
        except ValueError:
            size = 0
        if not 0 < size <= limit:
            raise RequestError(HTTPStatus.BAD_REQUEST, 'Choose a PDF under 100 MB.' if limit == MAX_PDF_BYTES else 'Invalid question request.')
        data = self.rfile.read(size)
        if len(data) != size:
            raise RequestError(HTTPStatus.BAD_REQUEST, 'The upload ended before the full file arrived.')
        return data

    def _dispatch(self, method):
        self._check_host()
        request_url = urlsplit(self.path)
        path = request_url.path
        if not path.startswith('/api/') and method == 'GET':
            return super().do_GET()
        if method == 'POST':
            origin = self.headers.get('Origin')
            if self.headers.get('X-KAQG-Request') != '1' or (origin and origin != f"http://{self.headers['Host']}"):
                raise RequestError(HTTPStatus.FORBIDDEN, 'Open the KAQG workspace before starting a job.')
        workspace = self.server.workspace
        if method == 'POST' and path == '/api/documents':
            filename = unquote(self.headers.get('X-PDF-Name', 'document.pdf'))
            if not re.fullmatch(r'[^/\\\x00-\x1f\x7f]{1,180}\.pdf', filename, flags=re.IGNORECASE) or len(filename.encode()) > 240:
                raise RequestError(HTTPStatus.BAD_REQUEST, 'Choose a PDF with a valid filename.')
            data = self._body(MAX_PDF_BYTES)
            if b'%PDF-' not in data[:1024]:
                raise RequestError(HTTPStatus.BAD_REQUEST, 'This file does not have a valid PDF header.')
            return self._json(workspace.upload(filename, data), HTTPStatus.ACCEPTED)
        parts = path.strip('/').split('/')
        if len(parts) in (3, 4) and parts[:2] == ['api', 'documents'] and DOCUMENT_ID.fullmatch(parts[2]):
            identity = parts[2]
            action = parts[3] if len(parts) == 4 else None
            if method == 'GET' and action is None:
                return self._json(workspace.status(identity))
            if method == 'GET' and action == 'syllabus':
                return self._json(workspace.syllabus(identity))
            if method == 'GET' and action in {'graph', 'questions', 'candidates'}:
                formats = parse_qs(request_url.query, keep_blank_values=True).get('format')
                if formats is None:
                    return self._respond(workspace.artifact(identity, action).read_bytes())
                export_format = formats[0] if len(formats) == 1 else None
                if action == 'graph':
                    if export_format not in GRAPH_DOWNLOADS:
                        raise RequestError(HTTPStatus.BAD_REQUEST, 'Choose JSON, GraphML, or CSV for the graph.')
                    content_type, filename = GRAPH_DOWNLOADS[export_format]
                    return self._respond(workspace.graph_download(identity, export_format), content_type, filename=filename)
                if export_format not in CONTENT_TYPES:
                    raise RequestError(HTTPStatus.BAD_REQUEST, 'Choose PDF, CSV, or JSON.')
                return self._respond(workspace.question_download(identity, action, export_format),
                                     CONTENT_TYPES[export_format], filename=f'{action}.{export_format}')
            if method == 'POST' and action == 'questions':
                try:
                    data = json.loads(self._body(512 * 1024))
                except ValueError:
                    data = None
                if not isinstance(data, dict):
                    raise RequestError(HTTPStatus.BAD_REQUEST, 'Invalid question request.')
                target = data.get('count')
                if type(target) is not int or not 1 <= target <= 50:
                    raise RequestError(HTTPStatus.BAD_REQUEST, 'Choose between 1 and 50 questions.')
                syllabus = data.get('syllabus', [])
                if not isinstance(syllabus, list) or any(not isinstance(topic, str) or not re.fullmatch(r'[a-f0-9]{24}', topic) for topic in syllabus):
                    raise RequestError(HTTPStatus.BAD_REQUEST, 'Invalid syllabus selection.')
                difficulty = data.get('difficulty', 'medium')
                balance = data.get('balance', False)
                if type(balance) is not bool:
                    raise RequestError(HTTPStatus.BAD_REQUEST, 'Balance must be on or off.')
                settings = None
                if balance:
                    values = data.get('balance_settings', {})
                    if not isinstance(values, dict) or values.keys() - {'extra_questions', 'max_seconds'}:
                        raise RequestError(HTTPStatus.BAD_REQUEST, 'Invalid balance settings.')
                    try:
                        settings = BalanceSettings(**values)
                    except ValueError as error:
                        raise RequestError(HTTPStatus.BAD_REQUEST, str(error)) from error
                return self._json(workspace.generate(identity, target, sorted(set(syllabus)), difficulty, settings), HTTPStatus.ACCEPTED)
            if method == 'POST' and action == 'cancel':
                return self._json(workspace.cancel(identity), HTTPStatus.ACCEPTED)
        raise RequestError(HTTPStatus.NOT_FOUND, 'This KAQG page could not be found.')

    def _handle(self, method):
        try:
            self._dispatch(method)
        except RequestError as error:
            self._json({'error': str(error)}, error.status)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):
        self._handle('GET')

    def do_POST(self):
        self._handle('POST')


def serve(port):
    workspace = Workspace(RUNTIME / 'web-runs')
    pid_file = RUNTIME / f'web-{port}.pid'

    def stop(_signal, _frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop)
    with ThreadingHTTPServer(('127.0.0.1', port), Handler) as server:
        server.workspace = workspace
        pid_file.write_text(f'{os.getpid()}\n', encoding='utf-8')
        print(f'KAQG workspace at http://127.0.0.1:{port}/ · PID {os.getpid()}', flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            workspace.close()
            pid_file.unlink(missing_ok=True)


def start_background(port):
    RUNTIME.mkdir(parents=True, exist_ok=True)
    log_file = RUNTIME / f'web-{port}.log'
    pid_file = RUNTIME / f'web-{port}.pid'
    with log_file.open('ab') as log:
        process = subprocess.Popen([sys.executable, '-u', __file__, '--port', str(port)], start_new_session=True,
                                   stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
    for _ in range(50):
        if process.poll() is not None:
            raise SystemExit(f'KAQG could not start. See {log_file}.')
        if pid_file.exists() and pid_file.read_text(encoding='utf-8').strip() == str(process.pid):
            print(f'KAQG workspace at http://127.0.0.1:{port}/')
            print(f'To stop it, run kill -TERM {process.pid}')
            return
        time.sleep(0.1)
    process.terminate()
    raise SystemExit(f'KAQG did not start in time. See {log_file}.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--background', action='store_true', help='Keep the loopback server alive after the launcher exits.')
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error('Choose a port between 1024 and 65535')
    if not (BUILD / 'index.html').is_file():
        parser.exit(1, 'Build the React frontend with npm run build in web/ first.\n')
    if args.background:
        start_background(args.port)
    else:
        serve(args.port)
