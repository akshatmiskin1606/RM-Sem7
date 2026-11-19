"""Run the KAQG PDF-to-question pipeline with temporary Fedora services."""

import argparse
from collections import Counter
from contextlib import ExitStack, redirect_stdout
from dataclasses import asdict
from itertools import count
import json
import os
from pathlib import Path
import random
import secrets
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from urllib.request import urlopen
from uuid import uuid4

from assessment_selector import BalanceSettings, CHECKPOINT_MESSAGE
from graph_reasoning import EvidenceQueue, evidence_paths, reasoning_details
from syllabus import build_syllabus, resolve_topics


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / ".kaqg-runtime"
OLLAMA_LOG = RUNTIME / "ollama.log"
NEO4J_IMAGE = "docker.io/library/neo4j:5.26.33-community"
MQTT_IMAGE = "docker.io/library/eclipse-mosquitto:2.0"
LOCAL_MODEL = "qwen3-vl:4b-instruct"
HOSTED_MODEL = "gpt-4o-mini"
DIFFICULTIES = {"easy": 30, "medium": 50, "hard": 70}

MOSQUITTO_COMMAND = """
set -eu
mosquitto_passwd -b -c /tmp/kaqg-passwords kaqg "$KAQG_MQTT_PASSWORD"
chown mosquitto:mosquitto /tmp/kaqg-passwords
chmod 600 /tmp/kaqg-passwords
printf 'listener 1883\nallow_anonymous false\npassword_file /tmp/kaqg-passwords\n' >/tmp/kaqg.conf
exec mosquitto -c /tmp/kaqg.conf
"""


def podman(*args, env=None):
    return subprocess.run(
        ["podman", *args], check=True, text=True, stdout=subprocess.PIPE, env=env,
    ).stdout.strip()


def remove_container(name):
    subprocess.run(["podman", "rm", "--force", "--ignore", name], stdout=subprocess.DEVNULL)


def start_container(cleanup, name, *args, env=None):
    follower = None

    def stop():
        try:
            remove_container(name)
        finally:
            if follower is not None:
                stop_process(follower)

    cleanup.callback(stop)
    podman("run", "--detach", "--rm", "--pull=never", "--name", name, *args, env=env)
    follower = subprocess.Popen(["podman", "logs", "--follow", "--timestamps", name],
                                stdout=sys.stderr, stderr=subprocess.STDOUT)


def mapped_port(container, port):
    binding = podman("port", container, f"{port}/tcp")
    return int(binding.rsplit(":", 1)[-1])


def wait_until(probe, description, timeout=30, process=None):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process is not None and process.poll() is not None:
            raise RuntimeError(f"{description} exited with status {process.returncode}.")
        try:
            return probe()
        except OSError:
            time.sleep(0.25)
    raise TimeoutError(f"Timed out waiting for {description}.")


def check_socket(address):
    with socket.socket(socket.AF_UNIX if isinstance(address, str) else socket.AF_INET) as conn:
        conn.settimeout(1)
        conn.connect(address)


def http_json(url):
    with urlopen(url, timeout=2) as response:
        return json.load(response)


def stop_process(process):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def start_process(cleanup, command, log=None, env=None):
    with ExitStack() as files:
        destination = sys.stderr
        if log is not None:
            descriptor = os.open(log, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
            destination = files.enter_context(os.fdopen(descriptor, "ab"))
        process = subprocess.Popen(command, stdout=destination, stderr=subprocess.STDOUT, env=env)
    cleanup.callback(stop_process, process)
    return process


def start_backend(cleanup, provider, model):
    if provider == "hosted":
        if not os.getenv("OPENAI_API_KEY"):
            raise RuntimeError("Set OPENAI_API_KEY locally to use the hosted backend.")
        return

    ollama = RUNTIME / "ollama/bin/ollama"
    if not ollama.is_file():
        raise RuntimeError("Install the local backend with bash tools/setup_local_model.sh.")
    with socket.socket() as address:
        address.bind(("127.0.0.1", 0))
        port = address.getsockname()[1]

    host = f"127.0.0.1:{port}"
    env = {
        **os.environ,
        "OLLAMA_HOST": host,
        "OLLAMA_MODELS": str(RUNTIME / "models"),
        "OLLAMA_NO_CLOUD": "1",
        "OLLAMA_NUM_PARALLEL": "1",
        "OLLAMA_CONTEXT_LENGTH": "8192",
    }
    process = start_process(cleanup, [str(ollama), "serve"], OLLAMA_LOG, env)
    url = f"http://{host}"
    try:
        models = wait_until(lambda: http_json(f"{url}/api/tags"), "Ollama", process=process)
    except (RuntimeError, TimeoutError) as error:
        raise RuntimeError(f"{error} See the model log at {OLLAMA_LOG}.") from error
    if not any(installed["name"] == model for installed in models["models"]):
        raise RuntimeError(f"Local model {model} is unavailable. Run bash tools/setup_local_model.sh.")
    os.environ["OPENAI_BASE_URL"] = f"{url}/v1"
    os.environ["OPENAI_API_KEY"] = "ollama"


def start_agent(cleanup, agent, hook="on_activate"):
    ready = threading.Event()
    errors = []
    original = getattr(agent, hook)

    def on_ready():
        try:
            original()
        except Exception as error:
            errors.append(error)
            raise
        finally:
            ready.set()

    setattr(agent, hook, on_ready)
    agent.start_thread()
    cleanup.callback(agent.terminate)
    if not ready.wait(20):
        raise TimeoutError(f"{agent.name} did not start.")
    if errors:
        raise RuntimeError(f"{agent.name} failed to start: {errors[0]}") from errors[0]


def read_saved_graph(path):
    graph = json.loads(path.read_text(encoding="utf-8"))
    if (
        not isinstance(graph, dict)
        or not isinstance(graph.get("pdf"), str)
        or not graph["pdf"]
        or type(graph.get("processed_pages")) is not int
        or graph["processed_pages"] < 1
        or graph.get("failed_pages") != []
        or not isinstance(graph.get("nodes"), list)
        or not graph["nodes"]
        or not isinstance(graph.get("relationships"), list)
        or not graph["relationships"]
    ):
        raise ValueError("Use a complete KAQG knowledge-graph export with no failed pages.")
    return graph


def restore_graph(tx, graph):
    nodes = tx.run(
        "UNWIND $rows AS row CREATE (n:$(row.labels)) SET n = row.properties "
        "RETURN row.id AS old_id, elementId(n) AS new_id", rows=graph["nodes"],
    )
    node_ids = {row["old_id"]: row["new_id"] for row in nodes}
    if len(node_ids) != len(graph["nodes"]):
        raise ValueError("The saved graph contains duplicate node IDs.")
    try:
        edges = [
            {**edge, "source": node_ids[edge["source"]], "target": node_ids[edge["target"]]}
            for edge in graph["relationships"]
        ]
    except KeyError as error:
        raise ValueError("A saved relationship refers to a missing node.") from error
    created = tx.run(
        "UNWIND $rows AS row "
        "MATCH (a) WHERE elementId(a) = row.source "
        "MATCH (b) WHERE elementId(b) = row.target "
        "CREATE (a)-[r:$(row.type)]->(b) SET r = row.properties",
        rows=edges,
    ).consume().counters.relationships_created
    if created != len(edges):
        raise RuntimeError("Neo4j could not restore all saved relationships.")


def run_kaqg(cleanup, args, name, temporary, broker_port, broker_password, model, saved_graph, syllabus):
    import app_helper

    from agentflow.core.agent import Agent
    from agentflow.core.parcel import BinaryParcel, TextParcel
    from evaluation.scq_evaluator import ScqEvaluator
    from generation.scq_generator import SingleChoiceGenerator
    from knowsys.knowledge_graph import KnowledgeGraph
    from retrieval.pdf_retriever import PdfRetriever
    from services.file_service import FileService
    from services.kg_service import KnowledgeGraphService, Topic
    from services.llm_service import LlmService

    mqtt = app_helper.config["broker"]["mqtt01"]
    mqtt.update(host="127.0.0.1", port=broker_port, username="kaqg", password=broker_password)
    agent_config = app_helper.get_agent_config()
    graph_directory = temporary / "graphs"
    graph_directory.mkdir()
    chat_options = {"model": model, "timeout": 120}
    if args.provider == "local":
        chat_options["max_tokens"] = 2048
    llm_config = {"name": "ChatGpt", "ChatGpt": chat_options}
    app_helper.report_progress("Connecting the KAQG workers to MQTT.")
    start_agent(cleanup, LlmService({**agent_config, "llm": llm_config}))
    start_agent(cleanup, KnowledgeGraphService({
        **agent_config, "kg": {"hostname": "127.0.0.1", "datapath": str(graph_directory)},
    }))
    if saved_graph is None:
        start_agent(cleanup, FileService(agent_config.copy(), str(temporary / "uploads")), "on_connected")
        start_agent(cleanup, PdfRetriever(agent_config.copy()), "on_connected")
    if not args.graph_only:
        start_agent(cleanup, SingleChoiceGenerator(agent_config.copy()))
        start_agent(cleanup, ScqEvaluator(agent_config.copy()))
    client = Agent("pdf-to-mcq", agent_config.copy())
    start_agent(cleanup, client, "on_connected")

    def request(topic, parcel, timeout):
        reply = client.publish_sync(topic, parcel, timeout=timeout)
        if reply.error:
            raise RuntimeError(f"{topic}: {reply.error}")
        return reply.content

    app_helper.report_progress("Opening the Neo4j knowledge graph.")
    graph = request(Topic.CREATE.value, TextParcel({"kg_name": name}), 195)
    if not graph.get("bolt_url"):
        raise RuntimeError("KAQG could not open the Neo4j graph.")

    if saved_graph is None:
        pdf_name = args.pdf.name
        print(f"Uploading {pdf_name} and extracting graph facts...", file=sys.stderr)
        upload = request(PdfRetriever.TOPIC_FILE_UPLOAD, BinaryParcel({
            "kg_name": name,
            "filename": pdf_name,
            "meta": {"title": args.pdf.stem},
            "content": args.pdf.read_bytes(),
        }), args.ingest_timeout)
        processed_pages = upload["processed_pages"]
        failed_pages = upload["failed_pages"]
        if not processed_pages:
            raise RuntimeError("KAQG extracted no readable pages from this PDF.")
    else:
        pdf_name = saved_graph["pdf"]
        processed_pages = saved_graph["processed_pages"]
        failed_pages = []
        print(f"Loading the saved graph from {args.from_graph}...", file=sys.stderr)

    with KnowledgeGraph(uri=graph["bolt_url"]) as knowledge_graph, knowledge_graph.session() as session:
        if saved_graph is not None:
            session.execute_write(restore_graph, saved_graph)
        nodes = {row["label"]: row["total"] for row in session.run(
            "MATCH (n) UNWIND labels(n) AS label RETURN label, count(*) AS total"
        )}
        relationships = session.run("MATCH ()-[r]->() RETURN count(r) AS total").single()["total"]
        if args.graph_output:
            app_helper.report_progress("Exporting the Neo4j nodes and relationships.")
            graph_export = {
                "pdf": pdf_name,
                "processed_pages": processed_pages,
                "failed_pages": failed_pages,
                "nodes": session.run(
                    "MATCH (n) RETURN elementId(n) AS id, labels(n) AS labels, properties(n) AS properties"
                ).data(),
                "relationships": session.run(
                    "MATCH (a)-[r]->(b) RETURN elementId(a) AS source, "
                    "elementId(b) AS target, type(r) AS type, properties(r) AS properties"
                ).data(),
            }
            with args.graph_output.open("x", encoding="utf-8") as destination:
                json.dump(graph_export, destination, ensure_ascii=False, indent=2)
                destination.write("\n")
            app_helper.report_progress(f"Saved the graph to {args.graph_output}.")
    if failed_pages:
        raise RuntimeError(f"KAQG failed to extract PDF pages {failed_pages}.")
    if not nodes.get("concept") or not nodes.get("fact") or not relationships:
        raise RuntimeError("Neo4j has no usable concept and fact graph.")
    print(f"Neo4j contains {nodes} and {relationships} relationships.", file=sys.stderr)

    result = graph_summary(args, model, pdf_name, processed_pages, nodes, relationships)
    if not args.graph_only:
        result["difficulty"] = args.difficulty
        if syllabus:
            result["syllabus"] = sorted(set(args.syllabus_topic))
        result["assessments"] = generate_questions(args, name, result, request, saved_graph, syllabus)
    return result


def graph_summary(args, model, pdf, pages, nodes, relationships):
    return {"pdf": pdf, "provider": args.provider, "model": model, "processed_pages": pages,
            "graph": {"nodes": nodes, "relationships": relationships}}


def run_graph_questions(args, name, model, saved_graph, syllabus, paths):
    import app_helper
    from evaluation.scq_evaluator import ScqEvaluator
    from generation.scq_generator import SingleChoiceGenerator
    from openai import APIError
    from services.llms.chat_llm import ChatLLM

    nodes = Counter(label for node in saved_graph["nodes"] for label in set(node["labels"]))
    node_ids = {node["id"] for node in saved_graph["nodes"]}
    relationships = saved_graph["relationships"]
    if len(node_ids) != len(saved_graph["nodes"]) or any(
        edge["source"] not in node_ids or edge["target"] not in node_ids for edge in relationships
    ):
        raise ValueError("The saved graph contains invalid node references.")
    if not nodes["concept"] or not nodes["fact"]:
        raise ValueError("The saved graph has no usable concept and fact graph.")
    result = graph_summary(args, model, saved_graph["pdf"], saved_graph["processed_pages"], dict(nodes), len(relationships))
    result.update(difficulty=args.difficulty, graph_reasoning=True)
    if syllabus:
        result["syllabus"] = sorted(set(args.syllabus_topic))

    options = {"model": model, "timeout": 120}
    tuned_local_model = args.provider == "local" and model == LOCAL_MODEL
    if args.provider == "local":
        options["max_tokens"] = 768 if tuned_local_model else 2048
    llm = ChatLLM(options)

    def prompt(params):
        schema = params.get("response_format", {}).get("json_schema", {})
        if tuned_local_model and schema.get("name") == "check_question_answer":
            params = {**params, "max_tokens": 160}
        try:
            return llm.generate_response(params)
        except APIError as error:
            raise RuntimeError(f"Inference failed: {error}") from error

    generator = SingleChoiceGenerator(app_helper.get_agent_config(), prompt=prompt)
    evaluator = ScqEvaluator(app_helper.get_agent_config(), prompt=prompt)
    workers = {generator.TOPIC_CREATE: generator.handle_create, evaluator.TOPIC_EVALUATE: evaluator.handle_evaluate}

    def request(topic, parcel, _timeout):
        return workers[topic](topic, parcel)

    app_helper.report_progress("Using paths from the saved graph directly.")
    result["assessments"] = generate_questions(args, name, result, request, saved_graph, syllabus, paths)
    return result


def evidence_by_page(graph):
    facts = {node["id"]: node["properties"] for node in graph["nodes"] if "fact" in node["labels"]}
    pages = {}
    for edge in graph["relationships"]:
        source = facts.get(edge["source"])
        target = facts.get(edge["target"])
        if not source or not target:
            continue
        page = source.get("page_number")
        if type(page) is int and page == target.get("page_number"):
            statement = f"{source['name']} {edge['type']} {target['name']}"
            pages.setdefault(page + 1, set()).add(statement)
    return [(page, sorted(rows)) for page, rows in sorted(pages.items(), key=lambda item: -len(item[1]))]


class BalanceDeadline(BaseException):
    """Interrupt optional inference even inside the generator's normal error handling."""


def collect_surplus(checkpoint, summary, assessments, collect, target, settings):
    import app_helper

    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=checkpoint.parent, delete=False) as temporary:
        staging = Path(temporary.name)
    try:
        staging.write_text(json.dumps({**summary, 'assessments': assessments}, ensure_ascii=False), encoding='utf-8')
        staging.replace(checkpoint)
    finally:
        staging.unlink(missing_ok=True)

    app_helper.report_progress(CHECKPOINT_MESSAGE)
    app_helper.report_progress(f'Looking for up to {settings.extra_questions} extra candidates in {settings.max_seconds} seconds.')

    def expire(_signal, _frame):
        raise BalanceDeadline

    handler = signal.signal(signal.SIGALRM, expire)
    try:
        signal.setitimer(signal.ITIMER_REAL, settings.max_seconds)
        collect(None, target + settings.extra_questions)
    except BalanceDeadline:
        app_helper.report_progress('The optional candidate window expired. Using the candidates already validated.')
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, handler)


def generate_questions(args, name, graph_summary, request, saved_graph, syllabus=(), paths=()):
    import app_helper
    from agentflow.core.parcel import TextParcel
    from evaluation.scq_evaluator import ScqEvaluator
    from generation.scq_generator import SingleChoiceGenerator

    assessments = []
    pages = []
    if args.resume_questions:
        partial = json.loads(args.resume_questions.read_text(encoding="utf-8"))
        if (
            not isinstance(partial, dict)
            or partial.get("pdf") != graph_summary["pdf"]
            or partial.get("graph") != graph_summary["graph"]
            or partial.get("syllabus", []) != graph_summary.get("syllabus", [])
            or partial.get("difficulty", args.difficulty) != args.difficulty
            or partial.get("graph_reasoning", False) != bool(paths)
        ):
            raise ValueError("The partial batch must match the saved graph, syllabus selection and difficulty mode.")
        assessments = partial.get("assessments")
        if (
            not isinstance(assessments, list)
            or len(assessments) >= args.questions
            or not all(SingleChoiceGenerator._is_valid_question(assessment) for assessment in assessments)
            or any(item.get("question_criteria", {}).get("difficulty") not in (None, DIFFICULTIES[args.difficulty])
                   for item in assessments)
        ):
            raise ValueError("Provide a valid partial batch with fewer than the requested total questions.")
        if not syllabus and not paths:
            pages = evidence_by_page(saved_graph)
        app_helper.report_progress(f"Resuming with {len(assessments)} previously accepted questions.")

    document = Path(graph_summary["pdf"]).stem
    seen_stems = {" ".join(item["question"]["stem"].casefold().split()) for item in assessments}
    previous_questions = []
    for item in assessments:
        question = item["question"]
        previous_questions.append({"stem": question["stem"], "answer": question[f"option_{question['answer']}"]})

    scoped_pages = []
    if syllabus and not paths:
        for title, evidence in syllabus:
            grouped = {}
            for link in evidence:
                if link.fact.pages:
                    grouped.setdefault(link.fact.pages[0], set()).add(link.fact.text)
            if grouped:
                scoped_pages.append((title, [(page, sorted(rows)) for page, rows in sorted(grouped.items())]))
        if not scoped_pages:
            raise ValueError("The selected graph topics have no page evidence.")

    evidence = EvidenceQueue(paths, args.difficulty, (item["question_criteria"]["graph_reasoning"] for item in assessments
                             if item.get("question_criteria", {}).get("graph_reasoning"))) if paths else None

    def collect(limit, target):
        attempts = count() if limit is None else range(limit)
        for attempt in attempts:
            chain = evidence.take() if evidence else None
            if evidence and chain is None:
                app_helper.report_progress("All distinct paths in this selection have been tried.")
                break
            index = len(assessments) + 1
            print(f"Generating question {index}/{target}...", file=sys.stderr)
            criteria = {
                "question_id": f"Q{index:03d}",
                "subject": name,
                "document": document,
                "section": None,
                "difficulty": DIFFICULTIES[args.difficulty],
                "language": args.language,
                "previous_questions": previous_questions,
            }
            if chain:
                details = reasoning_details(chain)
                source_pages = sorted({page for link in chain for page in link.fact.pages})
                criteria.update(graph_reasoning=details, graph_evidence=[link.fact.text for link in chain],
                                source_pages=source_pages)
                if len(source_pages) == 1:
                    criteria["source_page"] = source_pages[0]
                if len(syllabus) == 1:
                    title = syllabus[0][0]
                    criteria.update(section=list(title), syllabus_topic=title[-1])
                topics = {link.topic for link in chain if link.topic}
                app_helper.report_progress(f"{args.difficulty.title()} evidence · {len(details['nodes'])} connected nodes, "
                                           f"{len(chain)} relationships, {len(topics)} named topics.")
            elif scoped_pages:
                title, topic_pages = scoped_pages[attempt % len(scoped_pages)]
                page, rows = topic_pages[(attempt // len(scoped_pages)) % len(topic_pages)]
                criteria.update(section=list(title), syllabus_topic=title[-1], source_page=page,
                                graph_evidence=random.sample(rows, min(len(rows), 12)))
                app_helper.report_progress(f"Using {' → '.join(title)} · PDF page {page}.")
            elif pages:
                page, rows = pages[attempt % len(pages)]
                criteria["source_page"] = page
                criteria["graph_evidence"] = random.sample(rows, min(len(rows), 12))
                app_helper.report_progress(f"Using saved graph evidence from PDF page {page}.")
            try:
                assessment = request(SingleChoiceGenerator.TOPIC_CREATE, TextParcel(criteria), 750)
            except (RuntimeError, TimeoutError, ValueError) as error:
                if not evidence:
                    raise
                app_helper.report_progress(f"Candidate check failed. Trying a different path. {error}")
                continue
            if not SingleChoiceGenerator._is_valid_question(assessment):
                if evidence:
                    app_helper.report_progress("Candidate failed validation. Trying a different path.")
                continue
            stem = " ".join(assessment["question"]["stem"].casefold().split())
            if stem in seen_stems:
                continue
            app_helper.report_progress(f"Scoring question {index}/{target} with KAQG's evaluator.")
            try:
                scored = request(ScqEvaluator.TOPIC_EVALUATE, TextParcel(assessment), 195)
            except (RuntimeError, TimeoutError, ValueError) as error:
                print(f"Question scoring failed, retrying with a new candidate. {error}", file=sys.stderr)
                continue
            assessments.append(scored)
            seen_stems.add(stem)
            question = assessment["question"]
            answer_text = question[f"option_{question['answer']}"]
            previous_questions.append({"stem": question["stem"], "answer": answer_text})
            app_helper.report_progress(f"Accepted question {index}/{target}.")
            if len(assessments) == target:
                break

    attempt_limit = (args.questions - len(assessments)) * (5 if pages or syllabus else 3)
    collect(attempt_limit, args.questions)
    checkpoint = getattr(args, "balance_checkpoint", None)
    if checkpoint and len(assessments) == args.questions:
        graph_summary['balance_settings'] = asdict(args.balance_settings)
        collect_surplus(checkpoint, graph_summary, assessments, collect, args.questions, args.balance_settings)

    if not assessments:
        raise RuntimeError("KAQG could not verify a valid question from this PDF.")
    if len(assessments) < args.questions:
        print(f"KAQG generated {len(assessments)} unique questions from this PDF.", file=sys.stderr)
    return assessments


def run(args):
    saved_graph = read_saved_graph(args.from_graph) if args.from_graph else None
    syllabus = ()
    paths = ()
    if args.syllabus_topic or args.graph_reasoning:
        _, scopes = build_syllabus(saved_graph, args.syllabus_pdf)
        syllabus = resolve_topics(scopes, sorted(set(args.syllabus_topic)))
        if args.graph_reasoning:
            paths = evidence_paths(syllabus or [scopes['document']], args.difficulty)
    run_id = f"kaqg-{uuid4().hex[:12]}"
    model = args.model or (LOCAL_MODEL if args.provider == "local" else HOSTED_MODEL)
    sys.path.insert(0, str(ROOT / "src"))
    os.environ["WASTEPRO_CONFIG_PATH"] = str(ROOT / "kaqg-sample.toml")
    os.environ["KAQG_MODEL"] = model
    os.environ["NO_PROXY"] = ",".join(filter(None, [os.environ.get("NO_PROXY"), "127.0.0.1", "localhost"]))

    import app_helper
    app_helper.initialize("pdf_to_mcq")
    app_helper.config["show_progress"] = args.progress
    with ExitStack() as cleanup:
        temporary = Path(cleanup.enter_context(tempfile.TemporaryDirectory(prefix=f"{run_id}-")))
        app_helper.report_progress(f"Preparing the {args.provider} inference backend ({model}).")
        start_backend(cleanup, args.provider, model)
        if paths:
            result = run_graph_questions(args, run_id, model, saved_graph, syllabus, paths)
            if args.provider == "local":
                app_helper.report_progress("Stopping the temporary model server.")
            return result

        app_helper.report_progress("Starting a temporary rootless Podman API.")
        socket_path = str(temporary / "podman.sock")
        service_url = f"unix://{socket_path}"
        service = start_process(cleanup, ["podman", "system", "service", "--time=0", service_url])
        wait_until(lambda: check_socket(socket_path), "Podman API", process=service)
        os.environ["DOCKER_HOST"] = service_url

        app_helper.report_progress("Starting the Mosquitto broker.")
        broker = f"{run_id}-mqtt"
        password = secrets.token_hex(24)
        start_container(cleanup, broker, "--publish", "127.0.0.1::1883", "--env", "KAQG_MQTT_PASSWORD",
                        "--entrypoint", "/bin/sh", MQTT_IMAGE, "-c", MOSQUITTO_COMMAND,
                        env={**os.environ, "KAQG_MQTT_PASSWORD": password})
        port = mapped_port(broker, 1883)
        wait_until(lambda: check_socket(("127.0.0.1", port)), "Mosquitto")

        app_helper.report_progress("Starting Neo4j.")
        start_container(
            cleanup, run_id, "--publish", "127.0.0.1::7474", "--publish", "127.0.0.1::7687",
            "--env", "NEO4J_AUTH=none", "--env", "NEO4J_server_memory_heap_max__size=512m",
            "--env", "NEO4J_server_memory_pagecache_size=256m", NEO4J_IMAGE,
        )
        result = run_kaqg(cleanup, args, run_id, temporary, port, password, model, saved_graph, syllabus)
        app_helper.report_progress("Stopping the temporary workers, containers, and model server.")
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path, nargs="?", help="path to a local PDF")
    parser.add_argument("-n", "--questions", type=int, default=3)
    parser.add_argument("--difficulty", choices=DIFFICULTIES, default="medium")
    parser.add_argument("--language", default="English")
    parser.add_argument("--provider", choices=("local", "hosted"), default="local")
    parser.add_argument("--model", help="override the provider's default model")
    parser.add_argument("--ingest-timeout", type=int, default=1800, metavar="SECONDS")
    parser.add_argument("-o", "--output", type=Path, help="write JSON to a new file")
    parser.add_argument("--graph-output", type=Path, help="export Neo4j nodes and relationships to a new JSON file")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--graph-only", action="store_true", help="build and export a graph, then stop")
    mode.add_argument("--from-graph", type=Path, help="generate questions from a saved graph without a PDF")
    parser.add_argument("--resume-questions", type=Path, help="continue a partial question JSON to the requested total")
    parser.add_argument("--syllabus-topic", action="append", default=[], help="restrict questions to a saved graph topic ID")
    parser.add_argument("--syllabus-pdf", type=Path, help="original PDF used to identify section boundaries")
    parser.add_argument("--graph-reasoning", action="store_true", help="use connected graph paths for the selected difficulty")
    parser.add_argument("--balance-checkpoint", type=Path, help="save the requested quiz before collecting bounded surplus candidates")
    parser.add_argument("--balance-extra-questions", type=int, default=BalanceSettings.extra_questions,
                        help="maximum number of extra validated candidates for balancing")
    parser.add_argument("--balance-max-seconds", type=int, default=BalanceSettings.max_seconds,
                        help="time limit in seconds for generating and validating extra candidates")
    parser.add_argument("--progress", action="store_true", help="show the steps of the run as they happen")
    args = parser.parse_args()
    if args.from_graph:
        if args.pdf or args.graph_output:
            parser.error("--from-graph takes the place of the PDF and --graph-output")
        if not args.from_graph.is_file():
            parser.error("provide an existing KAQG graph export")
    elif not args.pdf or not args.pdf.is_file() or args.pdf.suffix.lower() != ".pdf":
        parser.error("provide an existing .pdf file")
    if args.graph_only and not args.graph_output:
        parser.error("--graph-only requires --graph-output")
    if args.resume_questions and (not args.from_graph or not args.resume_questions.is_file()):
        parser.error("--resume-questions requires --from-graph and an existing partial question JSON")
    if (args.syllabus_topic or args.graph_reasoning) and not args.from_graph:
        parser.error("--syllabus-topic and --graph-reasoning require --from-graph")
    if args.syllabus_pdf and not (args.syllabus_topic or args.graph_reasoning):
        parser.error("--syllabus-pdf requires a topic selection or --graph-reasoning")
    if args.syllabus_pdf and not args.syllabus_pdf.is_file():
        parser.error("provide the original PDF for --syllabus-pdf")
    if args.questions < 1 or args.ingest_timeout < 1:
        parser.error("questions and ingestion timeout must be positive")
    if args.output and args.output.exists():
        parser.error("the output file already exists")
    if args.balance_checkpoint:
        if not args.graph_reasoning or not args.output or args.provider != "local":
            parser.error("--balance-checkpoint requires local --graph-reasoning and --output")
        if args.balance_checkpoint.exists() or args.balance_checkpoint.resolve() == args.output.resolve():
            parser.error("use a separate new file for the balance checkpoint")
        try:
            args.balance_settings = BalanceSettings(args.balance_extra_questions, args.balance_max_seconds)
        except ValueError as error:
            parser.error(str(error))
    if args.graph_output and args.graph_output.exists():
        parser.error("the graph output file already exists")
    if args.output and args.graph_output and args.output.resolve() == args.graph_output.resolve():
        parser.error("use separate paths for question and graph outputs")

    try:
        with redirect_stdout(sys.stderr):
            result = run(args)
        output = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
        if args.output:
            with args.output.open("x", encoding="utf-8") as destination:
                destination.write(output)
            if args.graph_only:
                print(f"Saved graph summary to {args.output}")
            else:
                print(f"Saved {len(result['assessments'])} questions to {args.output}")
        else:
            print(output, end="")
        if args.graph_only:
            return 0
        return int(len(result["assessments"]) < args.questions)
    except KeyboardInterrupt:
        print("KAQG run interrupted.", file=sys.stderr)
        return 130
    except (RuntimeError, ValueError, OSError, subprocess.CalledProcessError) as error:
        print(f"KAQG run failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    def stop_on_term(_signal, _frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop_on_term)
    sys.exit(main())
