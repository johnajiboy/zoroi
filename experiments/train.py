"""Train the Q-learning agent and save the learning curve.

Runs several random seeds so the report can show the result is stable.

    python -m experiments.train --episodes 4000 --seeds 5
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import numpy as np

from app.agent import QAgent

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "experiments" / "results"


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--episodes", type=int, default=4000)
    p.add_argument("--seeds", type=int, default=5)
    p.add_argument("--save", action="store_true", help="save the seed-0 agent to models/qtable.json")
    args = p.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)

    curves = []
    for seed in range(args.seeds):
        agent = QAgent()
        curves.append(agent.train(args.episodes, seed=2026 + seed))
        if seed == 0 and args.save:
            agent.save(ROOT / "models" / "qtable.json")

    path = OUT / f"learning_curve_{args.episodes}.csv"
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["episode", "avg_reward_mean", "avg_reward_std", "harm_rate_mean", "human_rate_mean"])
        for i in range(len(curves[0])):
            rewards = [c[i]["avg_reward"] for c in curves]
            w.writerow([curves[0][i]["episode"], round(np.mean(rewards), 3), round(np.std(rewards), 3),
                        round(np.mean([c[i]["harm_rate"] for c in curves]), 3),
                        round(np.mean([c[i]["human_rate"] for c in curves]), 3)])
    print(f"Saved {path}")

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        x = [pt["episode"] for pt in curves[0]]
        mean = np.mean([[pt["avg_reward"] for pt in c] for c in curves], axis=0)
        std = np.std([[pt["avg_reward"] for pt in c] for c in curves], axis=0)
        fig, ax = plt.subplots(figsize=(7, 3.5))
        ax.plot(x, mean, color="#2B6CB0", lw=2, label=f"mean of {args.seeds} seeds")
        ax.fill_between(x, mean - std, mean + std, color="#2B6CB0", alpha=0.15, lw=0)
        ax.axhline(0, color="#999", lw=0.8, ls="--")
        ax.set_xlabel("Training episodes (simulated outages)")
        ax.set_ylabel("Average reward per 100")
        ax.spines[["top", "right"]].set_visible(False)
        ax.legend(frameon=False)
        fig.tight_layout()
        png = OUT / f"learning_curve_{args.episodes}.png"
        fig.savefig(png, dpi=160)
        print(f"Saved {png}")
    except ImportError:
        print("matplotlib not installed: skipped the chart")


if __name__ == "__main__":
    main()
