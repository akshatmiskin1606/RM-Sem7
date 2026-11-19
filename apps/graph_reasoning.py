"""Choose connected evidence for KAQG's difficulty levels."""

from collections import Counter, defaultdict
from itertools import islice
import random
import re

from syllabus import normalized


HOPS = {'easy': 1, 'medium': 2, 'hard': 3}


def topic_rank(path):
    topics = {link.topic for link in path if link.topic}
    if len({topic[0] for topic in topics}) > 1:
        return 2
    return int(len(topics) > 1)


def evidence_paths(scopes, difficulty):
    """Return simple paths whose links all belong to the allowed syllabus scopes."""
    depth = HOPS[difficulty]
    links = sorted({link for _title, evidence in scopes for link in evidence})
    adjacency = defaultdict(list)
    oriented = []
    # The export stores a separate node per page for the same named fact.
    for link in links:
        source, target = normalized(link.fact.source), normalized(link.fact.target)
        if source == target or not source.strip() or not target.strip():
            continue
        adjacency[source].append((target, link))
        adjacency[target].append((source, link))
        oriented.extend(((source, target, link), (target, source, link)))

    random.shuffle(oriented)
    for neighbors in adjacency.values():
        random.shuffle(neighbors)

    def extend(path, endpoint, visited):
        if len(path) == depth:
            yield path
            return
        neighbors = adjacency[endpoint]
        if difficulty == 'hard':
            neighbors = sorted(neighbors, key=lambda neighbor: topic_rank((*path, neighbor[1])), reverse=True)
        for target, link in neighbors:
            if target not in visited:
                yield from extend((*path, link), target, visited | {target})

    candidates = {}
    for source, target, first in oriented:
        for path in islice(extend((first,), target, {source, target}), 3):
            signature = tuple(sorted(link.fact.text for link in path))
            previous = candidates.get(signature)
            if previous is None or (difficulty == 'hard' and topic_rank(path) > topic_rank(previous)):
                candidates[signature] = path

    paths = list(candidates.values())
    if not paths:
        raise ValueError(f'This graph selection has too few connected facts for {difficulty.title()}. '
                         'Select more topics or choose a lower difficulty.')
    paths.sort(key=lambda path: (topic_rank(path) if difficulty == 'hard' else 0,
                                sum(bool(link.topic) for link in path)), reverse=True)
    return paths


def reasoning_details(path):
    nodes = {}
    links = []
    for location in path:
        fact = location.fact
        for name in (fact.source, fact.target):
            nodes.setdefault(normalized(name), name)
        links.append({'source': fact.source, 'relation': fact.relation, 'target': fact.target,
                      'pages': list(fact.pages), 'topic': list(location.topic)})
    return {'nodes': list(nodes.values()), 'links': links}


def link_key(source, relation, target):
    return normalized(source), normalized(relation), normalized(target)


class EvidenceQueue:
    """Prefer fresh facts and switch paths after a rejected candidate."""

    def __init__(self, paths, difficulty, previous=()):
        self._used = Counter()
        self._topics = Counter()
        known = set()
        for details in previous:
            keys = frozenset(link_key(link['source'], link['relation'], link['target']) for link in details['links'])
            known.add(keys)
            self._used.update(keys)
            self._topics.update({tuple(link['topic']) for link in details['links'] if link['topic']})

        self._pending = []
        for path in paths:
            keys = frozenset(link_key(link.fact.source, link.fact.relation, link.fact.target) for link in path)
            if keys in known:
                continue
            known.add(keys)
            topics = {link.topic for link in path if link.topic}
            names = {name.strip() for key in keys for name in (key[0], key[2])}
            navigation = sum(bool(re.fullmatch(r'page \d+|session \d+|ppt|ppts|study notes|memory line|handout', name))
                             for name in names)
            priority = (-topic_rank(path) if difficulty == 'hard' else 0, navigation)
            self._pending.append((path, keys, topics, priority))

    def take(self):
        if not self._pending:
            return None

        def rank(index):
            _path, keys, topics, priority = self._pending[index]
            return (*priority, sum(self._used[key] for key in keys), sum(self._topics[topic] for topic in topics))

        path, keys, topics, _priority = self._pending.pop(min(range(len(self._pending)), key=rank))
        self._used.update(keys)
        self._topics.update(topics)
        return path
