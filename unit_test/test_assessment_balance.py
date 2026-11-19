import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from threading import Event
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'apps'))
from assessment_selector import BalanceSettings, select_questions
import pdf_to_mcq
from serve_web import Workspace


def assessment(identity, topic, source):
    return {
        'question': {'stem': f'What follows from {source}?', 'answer': 'A', 'option_A': source},
        'question_criteria': {'question_id': identity, 'graph_reasoning': {'links': [
            {'source': source, 'relation': 'includes', 'target': topic, 'topic': [topic]},
        ]}},
    }


class AssessmentBalanceTest(unittest.TestCase):
    def test_balance_settings_validate_integers_and_preserve_defaults(self):
        self.assertEqual(BalanceSettings(), BalanceSettings(2, 30))
        self.assertEqual(BalanceSettings(50, 3600).max_seconds, 3600)
        for values in ((0, 30), (51, 30), (True, 30), (2, 0), (2, 3601), (2, 1.5), (2, '30')):
            with self.subTest(values=values), self.assertRaises(ValueError):
                BalanceSettings(*values)

    def test_selector_returns_original_items_and_balances_topics(self):
        items = [assessment('Q001', 'A', 'First'), assessment('Q002', 'A', 'Second'), assessment('Q003', 'B', 'Third')]
        original = json.dumps(items)
        selected, selection = select_questions(items, 2)
        self.assertEqual(selection['selected_candidate_ids'], ['Q001', 'Q003'])
        self.assertIs(selected[0], items[0])
        self.assertIs(selected[1], items[2])
        self.assertEqual(json.dumps(items), original)

    def test_selector_balances_large_pools_with_bounded_swaps(self):
        items = [assessment(f'Q{index:03}', 'ABC'[index // 12], f'Source {index}') for index in range(36)]
        selected, selection = select_questions(items, 12)
        self.assertEqual(selection['method'], 'local-swap')
        self.assertEqual(len(selected), 12)
        self.assertEqual({item['question_criteria']['graph_reasoning']['links'][0]['topic'][0] for item in selected},
                         {'A', 'B', 'C'})
        self.assertEqual((selected, selection), select_questions(items, 12))
        for item in selected:
            self.assertTrue(any(item is candidate for candidate in items))

    def test_deadline_interrupts_optional_inference_and_keeps_the_checkpoint(self):
        notices = []
        base = assessment('Q001', 'A', 'First')
        extra = assessment('Q002', 'B', 'Second')
        items = [base]
        with TemporaryDirectory() as directory:
            checkpoint = Path(directory) / 'quiz.json'
            real_timer = pdf_to_mcq.signal.setitimer
            timer_values = []

            def fast_timer(kind, seconds):
                timer_values.append(seconds)
                return real_timer(kind, 0.05 if seconds else 0)

            def inference(attempts, target):
                self.assertEqual((attempts, target), (None, 5))
                self.assertEqual(json.loads(checkpoint.read_text())['assessments'], [base])
                items.append(extra)
                try:
                    time.sleep(3)
                except Exception:
                    self.fail('The deadline must escape the model client’s normal error handler')

            with patch.dict(sys.modules, {'app_helper': SimpleNamespace(report_progress=notices.append)}):
                with patch.object(pdf_to_mcq.signal, 'setitimer', side_effect=fast_timer):
                    started = time.monotonic()
                    pdf_to_mcq.collect_surplus(checkpoint, {}, items, inference, 1, BalanceSettings(4, 17))
                    self.assertLess(time.monotonic() - started, 1)
            self.assertEqual(timer_values, [17, 0])
            self.assertEqual(items, [base, extra])
            self.assertEqual(json.loads(checkpoint.read_text())['assessments'], [base])
            self.assertTrue(any('expired' in message for message in notices))

    def test_workspace_publishes_checkpoint_then_two_downloads(self):
        with TemporaryDirectory() as directory:
            workspace, doc = self.workspace(directory)
            checkpoint_ready, finish = Event(), Event()
            items = [assessment('Q001', 'A', 'First'), assessment('Q002', 'A', 'Second'), assessment('Q003', 'B', 'Third')]

            def worker(_job, *args, on_checkpoint):
                checkpoint = args[args.index('--balance-checkpoint') + 1]
                self.assertEqual(args[args.index('--balance-extra-questions') + 1], 3)
                self.assertEqual(args[args.index('--balance-max-seconds') + 1], 45)
                checkpoint.write_text(json.dumps({'assessments': items[:2]}))
                on_checkpoint()
                checkpoint_ready.set()
                finish.wait(2)
                output = args[args.index('--output') + 1]
                output.write_text(json.dumps({'assessments': items}))
                return 0

            workspace._run = worker
            workspace.generate(doc.name, 2, balance_settings=BalanceSettings(3, 45))
            thread = workspace.active.thread
            try:
                self.assertTrue(checkpoint_ready.wait(2))
                self.assertEqual(workspace.status(doc.name)['job']['phase'], 'balancing')
                self.assertEqual(json.loads(workspace.artifact(doc.name, 'questions').read_text())['assessments'], items[:2])
            finally:
                finish.set()
                thread.join(3)

            state = workspace.status(doc.name)
            final = json.loads(workspace.artifact(doc.name, 'questions').read_text())
            pool = json.loads(workspace.artifact(doc.name, 'candidates').read_text())
            self.assertEqual(state['job']['status'], 'complete')
            self.assertEqual(state['job']['balance_settings'], {'extra_questions': 3, 'max_seconds': 45})
            self.assertEqual(state['questions']['candidates']['target'], 5)
            self.assertEqual(pool['assessments'], items)
            self.assertEqual(final['assessments'], [items[0], items[2]])

    def test_opt_out_requests_only_the_original_count(self):
        with TemporaryDirectory() as directory:
            workspace, doc = self.workspace(directory)
            items = [assessment('Q001', 'A', 'First')]

            def worker(_job, *args):
                self.assertNotIn('--balance-checkpoint', args)
                self.assertEqual(args[args.index('--questions') + 1], 1)
                args[args.index('--output') + 1].write_text(json.dumps({'assessments': items}))
                return 0

            workspace._run = worker
            workspace.generate(doc.name, 1)
            active = workspace.active
            if active:
                active.thread.join(3)
            state = workspace.status(doc.name)
            self.assertEqual(state['job']['status'], 'complete')
            self.assertNotIn('candidates', state['questions'])

    @staticmethod
    def workspace(directory):
        workspace = Workspace(Path(directory))
        doc = workspace.directory / ('f' * 32)
        doc.mkdir()
        (doc / 'state.json').write_text(json.dumps({
            'filename': 'document.pdf', 'graph': {'nodes': 4}, 'questions': None, 'job': {'status': 'complete'},
        }))
        return workspace, doc
