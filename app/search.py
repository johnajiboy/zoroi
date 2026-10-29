"""Root-cause search over failure hypotheses.

State  : a set of suspected failed services (at most two).
Goal   : the set explains every alerting service.
g(n)   : cost of the hypothesis. Each failure costs 1, plus penalties when the
         evidence argues against it (a healthy-looking service, or healthy services
         that would also have broken).
h(n)   : ceil(unexplained alerts / most alerts any one service can explain).
         Each extra failure costs at least 1 and explains at most `max_cov` alerts,
         so h never overestimates and A* returns the lowest-cost explanation.

BFS and greedy best-first are included as baselines for the experiments.
"""

from __future__ import annotations

import heapq
import itertools
import math
from collections import deque
from dataclasses import dataclass

from .services import DEPENDENCIES, NODES, upstream

MAX_FAILURES = 2


@dataclass
class Hypothesis:
    services: tuple[str, ...]
    g: float
    last: int


@dataclass
class SearchResult:
    best: Hypothesis | None
    second: Hypothesis | None
    expanded: int          # hypotheses expanded until the best one was found
    pool: list[str]        # candidate services considered


def _candidate_pool(alerting: list[str]) -> list[str]:
    seen = set(alerting)
    queue = deque(alerting)
    pool: list[str] = []
    while queue:
        n = queue.popleft()
        pool.append(n)
        for d in DEPENDENCIES[n]:
            if d not in seen:
                seen.add(d)
                queue.append(d)
    # neutral order: user-facing services first, so BFS gets no hint about the answer
    pool.sort(key=lambda n: (NODES[n]["x"], NODES[n]["y"]))
    return pool


def hypothesis_search(alerting: list[str], sick: set[str], mode: str = "astar") -> SearchResult:
    """mode: 'astar', 'bfs' or 'greedy'."""
    A = set(alerting)
    pool = _candidate_pool(alerting)
    cov: dict[str, set[str]] = {}
    cost: dict[str, float] = {}
    for n in pool:
        explained = [n, *upstream(n)]
        cov[n] = {x for x in explained if x in A}
        extra = sum(1 for x in explained if x not in A and x != n and x not in sick)
        healthy = n not in A and n not in sick
        cost[n] = 1 + 0.5 * extra + (2 if healthy else 0) + 0.2 * sum(1 for d in DEPENDENCIES[n] if d in sick)
    max_cov = max(len(c) for c in cov.values())

    def unexplained(h: tuple[str, ...]) -> int:
        covered: set[str] = set()
        for n in h:
            covered |= cov[n]
        return len(A - covered)

    def heuristic(h: tuple[str, ...]) -> int:
        return math.ceil(unexplained(h) / max_cov)

    def key(x: Hypothesis) -> float:
        if mode == "astar":
            return x.g + heuristic(x.services)
        if mode == "greedy":
            return unexplained(x.services)
        return len(x.services)  # bfs

    start = Hypothesis((), 0.0, -1)
    counter = itertools.count()  # tie-break: earlier hypotheses first
    if mode == "bfs":
        fifo: deque[Hypothesis] = deque([start])
    else:
        heap: list[tuple[float, int, Hypothesis]] = [(key(start), next(counter), start)]
    goals: list[Hypothesis] = []
    expanded = first_at = 0
    while (fifo if mode == "bfs" else heap) and len(goals) < 2:
        cur = fifo.popleft() if mode == "bfs" else heapq.heappop(heap)[2]
        expanded += 1
        if cur.services and unexplained(cur.services) == 0:
            # skip non-minimal explanations (a known explanation plus an extra service)
            if any(set(g.services) <= set(cur.services) for g in goals):
                continue
            goals.append(cur)
            if len(goals) == 1:
                first_at = expanded
            continue
        if len(cur.services) >= MAX_FAILURES:
            continue
        for i in range(cur.last + 1, len(pool)):
            child = Hypothesis(cur.services + (pool[i],), cur.g + cost[pool[i]], i)
            if mode == "bfs":
                fifo.append(child)
            else:
                heapq.heappush(heap, (key(child), next(counter), child))
    return SearchResult(goals[0] if goals else None, goals[1] if len(goals) > 1 else None, first_at, pool)


def root_cause(alerting: list[str], sick: set[str]) -> dict:
    """Run A* (plus BFS and greedy for comparison) and summarise the result."""
    a = hypothesis_search(alerting, sick, "astar")
    b = hypothesis_search(alerting, sick, "bfs")
    g = hypothesis_search(alerting, sick, "greedy")
    best, second = a.best, a.second
    confident = len(best.services) == 1 and (second is None or second.g - best.g >= 0.15)

    def name(h: Hypothesis | None) -> str:
        return " + ".join(NODES[n]["svc"] for n in h.services) if h else ""

    candidates = [
        {"services": list(h.services), "label": name(h), "cost": round(h.g, 2), "score": round(best.g / h.g, 3)}
        for h in (best, second) if h
    ]
    return {
        "best": list(best.services),
        "confident": confident,
        "candidates": candidates,
        "pool": a.pool,
        "stats": {
            "astar": a.expanded,
            "bfs": b.expanded, "bfs_pick": name(b.best), "bfs_correct": b.best.services == best.services,
            "greedy": g.expanded, "greedy_pick": name(g.best), "greedy_correct": g.best.services == best.services,
        },
    }
