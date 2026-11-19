import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'apps'))
from serve_web import Workspace


class GraphHistoryTest(unittest.TestCase):
    def test_existing_graphs_survive_restart_and_sort_by_saved_time(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            older = self.save_document(root, 'a' * 32, 100)
            recent = self.save_document(root, 'b' * 32, 200)
            self.save_document(root, 'c' * 32, 300, ready=False)
            missing = self.save_document(root, 'd' * 32, 400)
            (missing / 'knowledge-graph.json').unlink()
            invalid = self.save_document(root, 'e' * 32, 500)
            (invalid / 'state.json').write_text('invalid JSON')
            self.save_document(root, 'unrelated', 600)

            for workspace in (Workspace(root), Workspace(root)):
                self.assertEqual(workspace.history(), {
                    'documents': [
                        {'id': recent.name, 'filename': 'lesson.pdf', 'saved_at': 200},
                        {'id': older.name, 'filename': 'lesson.pdf', 'saved_at': 100},
                    ],
                    'active': None,
                })
                self.assertEqual(workspace.artifact(older.name, 'graph'), older / 'knowledge-graph.json')

    @staticmethod
    def save_document(root, identity, saved_at, *, ready=True):
        document = root / identity
        document.mkdir()
        graph = document / 'knowledge-graph.json'
        graph.write_text('{}')
        os.utime(graph, (saved_at, saved_at))
        (document / 'state.json').write_text(json.dumps({
            'id': identity,
            'filename': 'lesson.pdf',
            'graph': {'nodes': 2, 'relationships': 1, 'pages': 1} if ready else None,
            'job': {'status': 'complete' if ready else 'cancelled'},
        }))
        return document
