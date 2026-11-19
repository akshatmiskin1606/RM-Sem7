"""Export a saved KAQG knowledge graph for graph and spreadsheet tools."""

import csv
import io
import json
import re
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

import networkx as nx

from question_exports import spreadsheet_text


GRAPH_DOWNLOADS = {
    'json': ('application/json', 'knowledge-graph.json'),
    'graphml': ('application/graphml+xml', 'knowledge-graph.graphml'),
    'csv': ('application/zip', 'knowledge-graph-csv.zip'),
}
INVALID_XML_CHARACTERS = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]')


def display_name(properties):
    return str(properties.get('name') or properties.get('title') or '')


def xml_text(value):
    return INVALID_XML_CHARACTERS.sub('\ufffd', value)


def graphml(graph):
    exported = nx.MultiDiGraph(source_pdf=xml_text(graph['pdf']), processed_pages=graph['processed_pages'])
    node_ids = {}
    for index, node in enumerate(graph['nodes']):
        local_id = f'n{index}'
        node_ids[node['id']] = local_id
        properties = node['properties']
        exported.add_node(local_id, source_id=xml_text(str(node['id'])), name=xml_text(display_name(properties)),
                          labels=json.dumps(node['labels']), properties=json.dumps(properties))
        if type(properties.get('page_number')) is int:
            exported.nodes[local_id]['page_number'] = properties['page_number']

    for index, edge in enumerate(graph['relationships']):
        exported.add_edge(node_ids[edge['source']], node_ids[edge['target']], key=f'e{index}',
                          type=xml_text(edge['type']), properties=json.dumps(edge.get('properties', {})))

    return ('\n'.join(nx.generate_graphml(exported)) + '\n').encode('utf-8')


def csv_archive(graph):
    nodes = io.StringIO(newline='')
    node_writer = csv.writer(nodes)
    node_writer.writerow(('id', 'name', 'labels', 'page_number', 'properties'))
    for node in graph['nodes']:
        properties = node['properties']
        node_writer.writerow((spreadsheet_text(str(node['id'])), spreadsheet_text(display_name(properties)),
                              json.dumps(node['labels'], ensure_ascii=False), properties.get('page_number'),
                              json.dumps(properties, ensure_ascii=False)))

    relationships = io.StringIO(newline='')
    edge_writer = csv.writer(relationships)
    edge_writer.writerow(('source', 'target', 'type', 'properties'))
    for edge in graph['relationships']:
        source = spreadsheet_text(str(edge['source']))
        target = spreadsheet_text(str(edge['target']))
        relation = spreadsheet_text(edge['type'])
        edge_writer.writerow((source, target, relation, json.dumps(edge.get('properties', {}), ensure_ascii=False)))

    output = io.BytesIO()
    with ZipFile(output, 'w') as archive:
        archive.writestr(ZipInfo('nodes.csv'), nodes.getvalue().encode('utf-8-sig'), compress_type=ZIP_DEFLATED)
        archive.writestr(ZipInfo('relationships.csv'), relationships.getvalue().encode('utf-8-sig'), compress_type=ZIP_DEFLATED)
    return output.getvalue()
