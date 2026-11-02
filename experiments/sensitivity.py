"""Reward sensitivity: how much do the reward values change what the agent learns?

Trains the Q-learning agent with different harm penalties and human costs (several
seeds each), then evaluates every trained agent on the same unseen outages in the
standard environment, so the minutes are comparable across settings.

    python -m experiments.sensitivity --episodes 4000 --seeds 5
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import numpy as np

from app.agent import QAgent, evaluate
from app.simulator import HARM_PENALTY, HUMAN_MIN, OutageEnv

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "experiments" / "results"

# (parameter, OutageEnv keyword, default, values)
SWEEPS = [
    ("Harm penalty", "harm_penalty", HARM_PENALTY, [10, HARM_PENALTY, 50]),
    ("Human cost (min)", "human_min", HUMAN_MIN, [15, HUMAN_MIN, 40]),
]
METRICS = [("avg_recovery_min", "Avg recovery (min)"), ("made_worse_pct", "Made worse (%)"),
           ("escalated_pct", "Escalated (%)")]


def run(episodes: int, seeds: int, eval_episodes: int) -> list[dict]:
    """One row per (parameter, value): mean and standard deviation of each metric over seeds."""
    rows = []
    for name, key, default, values in SWEEPS:
        for value in values:
            results = []
            for seed in range(seeds):
                agent = QAgent()
                agent.train(episodes, seed=2026 + seed, env=OutageEnv(**{key: value}))
                results.append(evaluate(agent.policy(), eval_episodes))
            row = {"parameter": name, "value": value, "default": value == default}
            for m, _ in METRICS:
                vals = [r[m] for r in results]
                row[f"{m}_mean"] = round(float(np.mean(vals)), 2)
                row[f"{m}_std"] = round(float(np.std(vals)), 2)
            rows.append(row)
    return rows


def save_csv(rows: list[dict], path: Path) -> None:
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def save_chart(rows: list[dict], path: Path) -> bool:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return False
    fig, axes = plt.subplots(len(SWEEPS), len(METRICS), figsize=(10, 5.5))
    for i, (name, *_) in enumerate(SWEEPS):
        sub = [r for r in rows if r["parameter"] == name]
        x = np.arange(len(sub))
        for j, (m, label) in enumerate(METRICS):
            ax = axes[i, j]
            colors = ["#2B6CB0" if r["default"] else "#90B4DE" for r in sub]
            ax.bar(x, [r[f"{m}_mean"] for r in sub], yerr=[r[f"{m}_std"] for r in sub],
                   color=colors, capsize=3, width=0.6)
            top = max(r[f"{m}_mean"] + r[f"{m}_std"] for r in sub)
            ax.set_ylim(0, max(1.0, top * 1.15))  # keep the axis readable when every value is 0
            ax.set_xticks(x, [str(r["value"]) for r in sub])
            ax.set_xlabel(name)
            if i == 0:
                ax.set_title(label, fontsize=10)
            ax.spines[["top", "right"]].set_visible(False)
    fig.suptitle("Reward sensitivity (mean and std over seeds; dark bar = default)", fontsize=11)
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)
    return True


def print_table(rows: list[dict]) -> None:
    print(f"{'Setting':<26}{'Avg recovery':>16}{'Made worse':>16}{'Escalated':>16}")
    for r in rows:
        setting = f"{r['parameter']} = {r['value']}" + (" *" if r["default"] else "")
        cells = [f"{r[f'{m}_mean']:.1f} ± {r[f'{m}_std']:.1f}" for m, _ in METRICS]
        print(f"{setting:<26}{cells[0] + ' min':>16}{cells[1] + '%':>16}{cells[2] + '%':>16}")
    print("* default value")


def main(argv: list[str] | None = None) -> list[dict]:
    p = argparse.ArgumentParser()
    p.add_argument("--episodes", type=int, default=4000, help="training episodes per agent")
    p.add_argument("--seeds", type=int, default=5)
    p.add_argument("--eval-episodes", type=int, default=1000)
    p.add_argument("--out", type=Path, default=OUT)
    args = p.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)

    rows = run(args.episodes, args.seeds, args.eval_episodes)
    print_table(rows)
    csv_path = args.out / "reward_sensitivity.csv"
    save_csv(rows, csv_path)
    print(f"\nSaved {csv_path}")
    png = args.out / "reward_sensitivity.png"
    print(f"Saved {png}" if save_chart(rows, png) else "matplotlib not installed: skipped the chart")
    return rows


if __name__ == "__main__":
    main()
