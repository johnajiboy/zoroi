"""Q-learning agent that decides whether to act or escalate, plus baseline policies."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

import numpy as np

from .simulator import ACTIONS, N_ACTIONS, N_STATES, OutageEnv

# A policy maps (state index, list of valid action indices, rng) to an action index.
Policy = Callable[[int, list[int], np.random.Generator], int]

RUNBOOK = ["rollback", "scale", "restart", "failover", "restart"]  # per pattern, used by "always act"


class QAgent:
    def __init__(self, alpha: float = 0.1, gamma: float = 0.9):
        self.q = np.zeros((N_STATES, N_ACTIONS))
        self.alpha = alpha
        self.gamma = gamma

    # -- acting ------------------------------------------------------------------
    def greedy(self, state: int, valid: list[int]) -> int:
        return max(valid, key=lambda a: (self.q[state, a], -a))

    def act(self, state: int, valid: list[int], rng: np.random.Generator, epsilon: float = 0.0) -> int:
        if rng.random() < epsilon:
            return int(rng.choice(valid))
        return self.greedy(state, valid)

    def policy(self) -> Policy:
        return lambda s, valid, rng: self.greedy(s, valid)

    # -- learning ----------------------------------------------------------------
    def update(self, s: int, a: int, r: float, s2: int | None) -> None:
        target = r + (0.0 if s2 is None else self.gamma * float(np.max(self.q[s2])))
        self.q[s, a] += self.alpha * (target - self.q[s, a])

    def train(self, episodes: int = 4000, seed: int = 2026, eps_decay_episodes: int = 2600,
              window: int = 100) -> list[dict]:
        """Train on simulated outages. Returns the learning curve (one point per `window` episodes)."""
        env = OutageEnv()
        rng = np.random.default_rng(seed)
        env.reset(seed=seed)
        curve: list[dict] = []
        batch: list[dict] = []
        for ep in range(episodes):
            epsilon = max(0.05, 1 - ep / eps_decay_episodes)
            s, _ = env.reset()
            total_r, done, info = 0.0, False, {}
            while not done:
                a = self.act(s, env.valid_actions(), rng, epsilon)
                s2, r, done, _, info = env.step(a)
                self.update(s, a, r, None if done else s2)
                total_r += r
                s = s2
            batch.append({"reward": total_r, **info})
            if len(batch) == window:
                curve.append({
                    "episode": ep + 1,
                    "avg_reward": float(np.mean([b["reward"] for b in batch])),
                    "harm_rate": float(np.mean([b["harm"] for b in batch])),
                    "human_rate": float(np.mean([b["human"] for b in batch])),
                    "fixed_alone_rate": float(np.mean([b["fixed_alone"] for b in batch])),
                })
                batch = []
        return curve

    # -- persistence -------------------------------------------------------------
    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"actions": ACTIONS, "q": self.q.round(4).tolist()}, indent=1))

    @classmethod
    def load(cls, path: Path) -> "QAgent":
        agent = cls()
        agent.q = np.array(json.loads(path.read_text())["q"], dtype=float)
        return agent


# -- baselines -------------------------------------------------------------------
def always_act(state: int, valid: list[int], rng) -> int:
    """Follows a fixed runbook for the pattern and never asks for help first."""
    pattern, attempt = state // 4, state % 2
    preferred = RUNBOOK[pattern] if attempt == 0 else "restart"
    order = [preferred, "rollback", "restart", "scale", "failover"]
    for a in order:
        if ACTIONS.index(a) in valid:
            return ACTIONS.index(a)
    return ACTIONS.index("escalate")


def restart_first(state: int, valid: list[int], rng) -> int:
    """Always restart first, then call a human."""
    return ACTIONS.index("restart") if state % 2 == 0 else ACTIONS.index("escalate")


def always_escalate(state: int, valid: list[int], rng) -> int:
    return ACTIONS.index("escalate")


def random_policy(state: int, valid: list[int], rng) -> int:
    auto = [a for a in valid if ACTIONS[a] != "escalate"]
    return int(rng.choice(auto)) if auto else ACTIONS.index("escalate")


BASELINES: dict[str, Policy] = {
    "act": always_act, "rule": restart_first, "escalate": always_escalate, "random": random_policy,
}
POLICY_NAMES = {"rl": "Zoroi (RL agent)", "act": "Always act", "rule": "Restart first",
                "escalate": "Always escalate", "random": "Random"}


def evaluate(policy: Policy, episodes: int = 1000, seed: int = 777) -> dict:
    """Run a policy on unseen simulated outages."""
    env = OutageEnv()
    env.reset(seed=seed)
    rng = np.random.default_rng(seed)
    minutes, harm, human, alone = [], 0, 0, 0
    for _ in range(episodes):
        s, _ = env.reset()
        done, info = False, {}
        while not done:
            s, _, done, _, info = env.step(policy(s, env.valid_actions(), rng))
        minutes.append(info["minutes"])
        harm += info["harm"]
        human += info["human"]
        alone += info["fixed_alone"]
    return {
        "avg_recovery_min": round(float(np.mean(minutes)), 1),
        "made_worse_pct": round(100 * harm / episodes, 1),
        "escalated_pct": round(100 * human / episodes, 1),
        "fixed_alone_pct": round(100 * alone / episodes, 1),
    }
