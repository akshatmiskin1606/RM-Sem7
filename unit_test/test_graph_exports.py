import csv
import io
import json
from pathlib import Path
import sys
import unittest
from zipfile import ZipFile

import networkx as nx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'apps'))
from graph_exports import csv_archive, graphml


class GraphExportsTest(unittest.TestCase):
    def setUp(self):
        self.graph = {
            'pdf': 'Example.pdf',
            'processed_pages': 1,
            'nodes': [
                {'id': '4:graph:0', 'labels': ['fact', 'example'],
                 'properties': {'name': '=水 & ice', 'page_number': 0, 'aliases': ['water']}},
                {'id': '4:graph:1', 'labels': ['concept'], 'properties': {'name': 'Solid <state>'}},
            ],
            'relationships': [
                {'source': '4:graph:0', 'target': '4:graph:1', 'type': 'is_a', 'properties': {}},
                {'source': '4:graph:0', 'target': '4:graph:1', 'type': 'forms', 'properties': {'pages': [1]}},
                {'source': '4:graph:1', 'target': '4:graph:1', 'type': 'related_to'},
            ],
        }

    def test_graphml_preserves_directed_edges_and_metadata(self):
        result = nx.read_graphml(io.BytesIO(graphml(self.graph)), force_multigraph=True)
        self.assertTrue(result.is_directed())
        self.assertEqual(result.graph['source_pdf'], 'Example.pdf')
        self.assertEqual(len(result), 2)
        self.assertEqual(result.number_of_edges('n0', 'n1'), 2)
        self.assertEqual(result.number_of_edges('n1', 'n1'), 1)
        self.assertEqual(result.nodes['n0']['source_id'], '4:graph:0')
        self.assertEqual(result.nodes['n0']['name'], '=水 & ice')
        self.assertEqual(result.nodes['n0']['page_number'], 0)
        self.assertEqual(json.loads(result.nodes['n0']['properties']), self.graph['nodes'][0]['properties'])
        self.assertEqual(json.loads(result.edges['n0', 'n1', 'e1']['properties']), {'pages': [1]})

    def test_csv_archive_contains_both_tables_and_safe_cells(self):
        with ZipFile(io.BytesIO(csv_archive(self.graph))) as data:
            self.assertEqual(data.namelist(), ['nodes.csv', 'relationships.csv'])
            nodes = list(csv.DictReader(io.StringIO(data.read('nodes.csv').decode('utf-8-sig'))))
            edges = list(csv.DictReader(io.StringIO(data.read('relationships.csv').decode('utf-8-sig'))))
        self.assertEqual(nodes[0]['name'], "'=水 & ice")
        self.assertEqual(nodes[0]['page_number'], '0')
        self.assertEqual(json.loads(nodes[0]['labels']), ['fact', 'example'])
        self.assertEqual(json.loads(nodes[0]['properties']), self.graph['nodes'][0]['properties'])
        self.assertEqual([(edge['source'], edge['target'], edge['type']) for edge in edges], [
            (edge['source'], edge['target'], edge['type']) for edge in self.graph['relationships']
        ])
