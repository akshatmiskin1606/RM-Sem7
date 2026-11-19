"""Map a saved KAQG graph to a document outline and scoped question evidence."""

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
import re
import unicodedata


@dataclass
class Branch:
    id: str
    title: str
    kind: str
    children: list['Branch'] = field(default_factory=list)
    materials: set['FactLink'] = field(default_factory=set)

    def add(self, title, kind):
        identity = sha256(f'{self.id}/{len(self.children)}/{title}'.encode()).hexdigest()[:24]
        child = Branch(identity, title, kind)
        self.children.append(child)
        return child


@dataclass(frozen=True, order=True)
class FactLink:
    source_id: str
    target_id: str
    source: str
    relation: str
    target: str
    pages: tuple[int, ...]

    @property
    def text(self):
        return f'{self.source} {self.relation} {self.target}'


@dataclass(frozen=True, order=True)
class LocatedLink:
    topic: tuple[str, ...]
    fact: FactLink


def fact_links(graph, facts=None):
    if facts is None:
        facts = {node['id']: node['properties'] for node in graph['nodes'] if 'fact' in node['labels']}
    for edge in graph['relationships']:
        source, target = edge['source'], edge['target']
        if source not in facts or target not in facts:
            continue
        pages = {page + 1 for page in (facts[source].get('page_number'), facts[target].get('page_number')) if type(page) is int}
        yield FactLink(source, target, facts[source]['name'], edge['type'], facts[target]['name'],
                       tuple(sorted(pages)))


def normalized(text):
    return ' ' + re.sub(r'[^\w]+', ' ', unicodedata.normalize('NFKC', text).casefold()).strip() + ' '


def pdf_outline(path):
    """Return heading positions and text lines, preserving same-page boundaries."""
    import pymupdf

    records = []
    font_use = Counter()
    with pymupdf.open(path) as pdf:
        bookmarks = pdf.get_toc(simple=False)
        page_count = len(pdf)
        for page in pdf:
            flags = pymupdf.TEXTFLAGS_DICT & ~pymupdf.TEXT_PRESERVE_IMAGES
            for block in page.get_text('dict', flags=flags, sort=True)['blocks']:
                for line in block.get('lines', []):
                    spans = line['spans']
                    text = ''.join(span['text'] for span in spans).strip()
                    if not text:
                        continue
                    top = line['bbox'][1]
                    if top > page.rect.height * 0.9 and re.search(r'\b(?:page\s+)?\d+\s*$', text, re.I):
                        continue
                    size = round(max(span['size'] for span in spans), 1)
                    bold = any(span['flags'] & pymupdf.TEXT_FONT_BOLD for span in spans if span['size'] >= size - 0.1)
                    font_use[size] += len(text)
                    records.append((page.number, top, block['number'], text, size, bold))

    if not records:
        return None, [], {}

    if bookmarks:
        headings = {}
        by_page = defaultdict(list)
        for position, (page, *_rest) in enumerate(records):
            by_page[page].append(position)
        for depth, title, page, destination in bookmarks:
            positions = by_page.get(page - 1, [])
            if not positions or not title.strip():
                continue
            match = next((pos for pos in positions if normalized(records[pos][3]) == normalized(title)), None)
            point = destination.get('to')
            if match is None and point is not None:
                match = next((pos for pos in positions if records[pos][1] >= point.y - 3), None)
            if match is None and sum(bookmark[2] == page for bookmark in bookmarks) == 1:
                match = positions[0]
            if match is not None and match not in headings:
                headings[match] = (depth, title.strip(), 1)
        if headings:
            return None, records, headings

    body_size = font_use.most_common(1)[0][0]
    candidates = {index for index, (_p, _y, _b, text, size, bold) in enumerate(records)
                  if bold and size >= body_size + 1.4 and len(text) <= 180}
    chapter_sizes = Counter(records[index][4] for index in candidates
                            if re.match(r'^(?:chapter|session|unit|module|lecture|lesson)\s+[\w]+\b', records[index][3], re.I))
    primary_size = chapter_sizes.most_common(1)[0][0] if chapter_sizes else None
    cover = None
    first = next(iter(sorted(candidates)), None)
    if first is not None and records[first][0] == 0 and page_count > 1:
        later_sizes = [records[index][4] for index in candidates if records[index][0] > 0]
        if later_sizes and records[first][4] > max(later_sizes) + 1:
            cover = records[first][3]
            candidates = {index for index in candidates if records[index][0] != 0}
    sizes = sorted({records[index][4] for index in candidates}, reverse=True)
    levels = {size: index + 1 for index, size in enumerate(sizes)}
    if primary_size:
        levels = {size: 1 + sum(primary_size >= other > size for other in sizes) for size in sizes}
    headings = {}
    remaining = set(candidates)
    for index in sorted(candidates):
        if index not in remaining:
            continue
        page, _top, block, title, size, _bold = records[index]
        end = index + 1
        while end in remaining and (records[end][0], records[end][2], records[end][4]) == (page, block, size):
            if re.match(r'^\d+[.)]\s|^(?:chapter|session|unit|module)\s', records[end][3], re.I):
                break
            title += ' ' + records[end][3]
            remaining.remove(end)
            end += 1
        headings[index] = (levels[size], title, end - index)
    return cover, records, headings


def pdf_branches(root, records, headings):
    """Group text under its exact heading, including adjacent chapters on one page."""
    positions = iter(enumerate(records))
    hierarchy = [(0, root)]
    sections = {}
    skip_contents = False
    for index, (page, _top, _block, text, _size, _bold) in positions:
        if index in headings:
            level, title, lines = headings[index]
            for _ in range(lines - 1):
                next(positions, None)
            skip_contents = normalized(title).strip() in {'contents', 'table of contents'}
            if skip_contents:
                continue
            while hierarchy[-1][0] >= level:
                hierarchy.pop()
            parent = hierarchy[-1][1]
            branch = parent.add(title, 'chapter' if parent is root else 'subtopic')
            hierarchy.append((level, branch))
            sections[branch.id] = (branch, defaultdict(list))
            text = title
        if not skip_contents and hierarchy[-1][1] is not root:
            sections[hierarchy[-1][1].id][1][page + 1].append(text)
    return sections.values()


def structural_branches(root, nodes, relationships):
    """Reuse KAQG part_of / include_in / is_a when its exported graph has sections."""
    sections = defaultdict(list)
    concepts = defaultdict(set)
    fact_ids = defaultdict(set)
    for edge in relationships:
        source, target, relation = edge['source'], edge['target'], edge['type']
        if relation == 'part_of' and 'structure' in nodes[source]['labels']:
            sections[target].append(source)
        elif relation == 'include_in' and 'concept' in nodes[source]['labels']:
            concepts[target].add(source)
        elif relation == 'is_a' and 'fact' in nodes[source]['labels']:
            fact_ids[target].add(source)

    seen = set()

    def visit(parent, identity):
        if identity in seen:
            return
        seen.add(identity)
        for section in sections[identity]:
            if section in seen:
                continue
            branch = parent.add(nodes[section]['properties']['name'], 'chapter' if parent is root else 'subtopic')
            yield branch, set().union(*(fact_ids[concept] for concept in concepts[section]))
            yield from visit(branch, section)

    for identity, node in nodes.items():
        if 'document' in node['labels']:
            yield from visit(root, identity)


def attach_evidence(branch, allowed, edges):
    keywords = {}
    for fact in edges:
        if fact.source_id not in allowed or fact.target_id not in allowed:
            continue
        branch.materials.add(fact)
        for title in (fact.source, fact.target):
            key = normalized(title)
            if key not in keywords:
                keywords[key] = branch.add(title, 'keyword')
            keywords[key].materials.add(fact)


def build_syllabus(graph, pdf=None):
    nodes = {node['id']: node for node in graph['nodes']}
    facts = {identity: node['properties'] for identity, node in nodes.items() if 'fact' in node['labels']}
    title = next((node['properties'].get('name') for node in nodes.values() if 'document' in node['labels']), None)
    root = Branch('document', title or Path(graph['pdf']).stem, 'document')
    edges = tuple(fact_links(graph, facts))
    by_page = defaultdict(dict)
    for identity, fact in facts.items():
        if type(fact.get('page_number')) is int:
            aliases = [fact['name'], *(fact.get('aliases') or [])]
            by_page[fact['page_number'] + 1][identity] = [normalized(alias) for alias in aliases if isinstance(alias, str) and len(alias.strip()) > 1]
    cover, records, headings = pdf_outline(pdf) if pdf else (None, [], {})
    if cover:
        root.title = cover
    if headings:
        for branch, pages in pdf_branches(root, records, headings):
            allowed = set()
            for page, lines in pages.items():
                text = normalized(' '.join(lines))
                allowed.update(identity for identity, terms in by_page[page].items() if any(term in text for term in terms))
            attach_evidence(branch, allowed, edges)
    if not root.children or not any(child.materials or child.children for child in root.children):
        root.children.clear()
        for branch, allowed in structural_branches(root, nodes, graph['relationships']):
            attach_evidence(branch, allowed, edges)
    if not root.children:
        for page, identities in sorted(by_page.items()):
            attach_evidence(root.add(f'Page {page}', 'page'), identities, edges)

    scopes = {}

    def build_view(branch, parents):
        path = (*parents, branch.title)
        origin = parents[1:] if branch.kind == 'keyword' else path[1:]
        # A page fallback gives provenance but does not define a topic.
        if origin and re.fullmatch(r'Page \d+', origin[0]):
            origin = ()
        material = {LocatedLink(origin, fact) for fact in branch.materials}
        children = []
        for child in sorted(branch.children, key=lambda child: child.kind == 'keyword'):
            view, child_material = build_view(child, path)
            children.append(view)
            material.update(child_material)
        if material and branch is not root:
            scopes[branch.id] = (path[1:], tuple(sorted(material)))
        view = {'id': branch.id, 'title': branch.title, 'kind': branch.kind, 'children': children,
                'selectable': branch.id in scopes}
        return view, material

    outline, material = build_view(root, ())
    located = {link.fact for link in material}
    material.update(LocatedLink((), fact) for fact in edges if fact not in located)
    scopes['document'] = ((), tuple(sorted(material)))
    return outline, scopes


def resolve_topics(scopes, selected):
    if any(topic not in scopes or topic == 'document' for topic in selected):
        raise ValueError('Select syllabus topics that have graph evidence for this PDF.')
    return [scopes[topic] for topic in selected]
