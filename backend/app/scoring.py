"""Deterministic scoring strategies. No HTTP, persistence, or model dependency."""
from collections.abc import Callable


def exact_set(expected: list[str], actual: list[str], max_score: int) -> int:
    return max_score if set(expected) == set(actual) else 0


STRATEGIES: dict[tuple[str, int], Callable[[list[str], list[str], int], int]] = {
    ('single', 1): exact_set,
    ('multiple', 1): exact_set,
}


def score(strategy: str, version: int, expected: list[str], actual: list[str], max_score: int) -> int:
    scorer = STRATEGIES.get((strategy, version))
    if not scorer:
        raise ValueError('Unsupported scoring policy version')
    return scorer(expected, actual, max_score)
