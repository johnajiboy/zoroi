"""Compare the trained agent with the baselines on unseen simulated outages.

    python -m experiments.evaluate --episodes 1000
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

from app.agent import BASELINES, POLICY_NAMES, QAgent, evaluate

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "experiments" / "results"


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--episodes", type=int, default=1000)
    p.add_argument("--train-episodes", type=int, default=4000)
    args = p.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)

    qpath = ROOT / "models" / "qtable.json"
    if qpath.exists():
        agent = QAgent.load(qpath)
    else:
        agent = QAgent()
        agent.train(args.train_episodes)

    rows = [{"policy": POLICY_NAMES["rl"], **evaluate(agent.policy(), args.episodes)}]
    for key, policy in BASELINES.items():
        rows.append({"policy": POLICY_NAMES[key], **evaluate(policy, args.episodes)})

    path = OUT / "policy_comparison.csv"
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    print(f"{'Responder':<20}{'Avg recovery':>14}{'Made worse':>12}{'Escalated':>11}{'Fixed alone':>13}")
    for r in rows:
        print(f"{r['policy']:<20}{r['avg_recovery_min']:>11} min{r['made_worse_pct']:>11}%"
              f"{r['escalated_pct']:>10}%{r['fixed_alone_pct']:>12}%")
    print(f"\nSaved {path}")


if __name__ == "__main__":
    main()
