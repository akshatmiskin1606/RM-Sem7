"""Local selection of a quiz from validated candidates."""

from dataclasses import dataclass
from itertools import combinations
from math import comb
import re


CHECKPOINT_MESSAGE = 'Quiz saved. Checking for extra candidates.'
MAX_EXTRA_QUESTIONS = 50
MAX_EXTRA_SECONDS = 3600
EXACT_SUBSET_LIMIT = 2000
MAX_SWAP_PASSES = 8


@dataclass(frozen=True)
class BalanceSettings:
    extra_questions: int = 2
    max_seconds: int = 30

    def __post_init__(self):
        if type(self.extra_questions) is not int or not 1 <= self.extra_questions <= MAX_EXTRA_QUESTIONS:
            raise ValueError(f'Choose between 1 and {MAX_EXTRA_QUESTIONS} extra questions.')
        if type(self.max_seconds) is not int or not 1 <= self.max_seconds <= MAX_EXTRA_SECONDS:
            raise ValueError(f'Choose between 1 and {MAX_EXTRA_SECONDS} seconds of extra generation time.')


def normalized(text):
    return ' '.join(text.casefold().split())


def overlap(left, right):
    return len(left & right) / len(left | right) if left or right else 0


def improve_by_swapping(selected, linear, pair_costs, stems, ids):
    """Improve the first distinct quiz with a bounded number of single swaps."""
    for _ in range(MAX_SWAP_PASSES):
        selected_stems = {stems[index] for index in selected}
        costs = [weight + sum(pair_costs[index][member] for member in selected)
                 for index, weight in enumerate(linear)]
        best = None
        for incoming in range(len(ids)):
            if incoming in selected:
                continue
            for outgoing in selected:
                if stems[incoming] in selected_stems and stems[incoming] != stems[outgoing]:
                    continue
                change = round(costs[incoming] - costs[outgoing] - pair_costs[incoming][outgoing], 12)
                rank = (change, ids[incoming], ids[outgoing])
                if change < 0 and (best is None or rank < best):
                    best, swap = rank, (outgoing, incoming)
        if best is None:
            break
        outgoing, incoming = swap
        selected = sorted(incoming if index == outgoing else index for index in selected)
    return selected


def select_questions(candidates, target):
    """Return original assessments selected for topic balance and low overlap."""
    size = len(candidates)
    if not 0 < target <= size <= target + MAX_EXTRA_QUESTIONS:
        raise ValueError(f'Balance requires the requested number of questions and at most {MAX_EXTRA_QUESTIONS} extras.')

    ids, stems, tokens, triples, topics, pages = [], [], [], [], [], []
    for item in candidates:
        choices = item['question_criteria']
        links = choices.get('graph_reasoning', {}).get('links', [])
        stem = normalized(item['question']['stem'])
        ids.append(choices['question_id'])
        stems.append(stem)
        tokens.append(set(re.findall(r'\w+', stem)))
        triples.append({tuple(normalized(link[key]) for key in ('source', 'relation', 'target')) for link in links})
        topics.append({tuple(link['topic']) for link in links if link['topic']})
        source_pages = choices.get('source_pages') or [choices.get('source_page')]
        pages.append({page for page in source_pages if page is not None})

    if len(set(ids)) != len(ids):
        raise ValueError('Candidate IDs must be unique.')

    chapters = {path[0] for paths in topics for path in paths}
    if chapters:
        depth = 2 if len(chapters) == 1 else 1
        groups = [{path[:depth] for path in paths} for paths in topics]
    else:
        groups = pages
    buckets = set().union(*groups)
    shares = [{bucket: 1 / len(group) for bucket in sorted(group)} for group in groups]
    expected_share = target / len(buckets) if buckets else 0
    coverage_scale = target ** 2
    pair_count = max(1, comb(target, 2))
    # Expand squared coverage error into individual and pair costs. Its constant term is common to all quizzes.
    linear = [sum(value ** 2 - 2 * expected_share * value for value in share.values()) / coverage_scale
              for share in shares]
    pair_costs = [[0.0] * size for _ in candidates]
    for left, right in combinations(range(size), 2):
        word_overlap = overlap(tokens[left], tokens[right])
        redundancy = (0.75 * overlap(triples[left], triples[right]) + 0.25 * word_overlap
                      if triples[left] and triples[right] else word_overlap)
        shared_coverage = sum(value * shares[right].get(bucket, 0) for bucket, value in shares[left].items())
        pair_costs[left][right] = pair_costs[right][left] = 2 * shared_coverage / coverage_scale + redundancy / pair_count

    unique = {}
    for index, stem in enumerate(stems):
        unique.setdefault(stem, index)
    if len(unique) < target:
        raise ValueError('There are too few distinct questions to balance this quiz.')

    if comb(size, target) <= EXACT_SUBSET_LIMIT:
        def rank(subset):
            cost = sum(linear[index] for index in subset) + sum(pair_costs[a][b] for a, b in combinations(subset, 2))
            return round(cost, 12), tuple(sorted(ids[index] for index in subset))

        eligible = (subset for subset in combinations(range(size), target) if len({stems[index] for index in subset}) == target)
        selected, method = min(eligible, key=rank), 'exact'
    else:
        selected = improve_by_swapping(list(unique.values())[:target], linear, pair_costs, stems, ids)
        method = 'local-swap'

    return [candidates[index] for index in selected], {
        'method': method, 'candidate_count': size,
        'selected_candidate_ids': [ids[index] for index in selected],
    }
