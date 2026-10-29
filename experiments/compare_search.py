"""Compare A*, BFS and greedy best-first root-cause search.

Generates random outages on the service graph (one or two failed services,
plus some missing alerts as noise) and measures accuracy and hypotheses
expanded.

    python -m experiments.compare_search --outages 200
"""

from __future__ import annotations

import argparse
import csv
import random
import time
from pathlib import Path

from app.search import hypothesis_search
from app.services import NODES, is_external, upstream

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "experiments" / "results"
FAILABLE = [n for n in NODES if n not in ("web",)]


def random_outage(rng: random.Random, p_double: float, p_missing: float):
    k = 2 if rng.random() < p_double else 1
    roots = rng.sample(FAILABLE, k)
    affected: list[str] = []
    for r in roots:
        for u in [r, *upstream(r)]:
            if u not in affected:
                affected.append(u)
    alerting = [n for n in affected if not is_external(n)]
    # monitoring is imperfect: some upstream alerts never fire
    alerting = [n for n in alerting if n in roots or rng.random() >= p_missing]
    if not alerting:
        return None
    sick = set(alerting) | {r for r in roots if is_external(r)}
    return set(roots), alerting, sick


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--outages", type=int, default=200)
    p.add_argument("--p-double", type=float, default=0.3)
    p.add_argument("--p-missing", type=float, default=0.1)
    p.add_argument("--seed", type=int, default=7)
    args = p.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)

    rng = random.Random(args.seed)
    stats = {m: {"correct": 0, "expanded": 0, "time_ms": 0.0, "n": 0} for m in ("astar", "bfs", "greedy")}
    by_size = {m: {1: [0, 0], 2: [0, 0]} for m in stats}
    made = 0
    while made < args.outages:
        o = random_outage(rng, args.p_double, args.p_missing)
        if not o:
            continue
        made += 1
        roots, alerting, sick = o
        for m in stats:
            t0 = time.perf_counter()
            r = hypothesis_search(alerting, sick, m)
            stats[m]["time_ms"] += (time.perf_counter() - t0) * 1000
            ok = r.best is not None and set(r.best.services) == roots
            stats[m]["correct"] += ok
            stats[m]["expanded"] += r.expanded
            stats[m]["n"] += 1
            by_size[m][len(roots)][0] += ok
            by_size[m][len(roots)][1] += r.expanded

    rows = []
    for m, s in stats.items():
        rows.append({"algorithm": m, "accuracy_pct": round(100 * s["correct"] / s["n"], 1),
                     "avg_expanded": round(s["expanded"] / s["n"], 1), "avg_time_ms": round(s["time_ms"] / s["n"], 3)})
    path = OUT / "search_comparison.csv"
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    print(f"{args.outages} outages ({int(args.p_double * 100)}% with two failures, "
          f"{int(args.p_missing * 100)}% of alerts missing)\n")
    print(f"{'Algorithm':<10}{'Accuracy':>10}{'Expanded':>10}{'Time':>12}")
    for r in rows:
        print(f"{r['algorithm']:<10}{r['accuracy_pct']:>9}%{r['avg_expanded']:>10}{r['avg_time_ms']:>9} ms")
    print("\nNote: accuracy is measured against the true injected failure. When alerts are missing, the")
    print("lowest-cost explanation can legitimately differ from the truth; discuss this in the report.")
    print(f"\nSaved {path}")


if __name__ == "__main__":
    main()
