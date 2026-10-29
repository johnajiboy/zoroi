"""Outage simulator used to train the reinforcement learning agent.

Each episode is one practice outage. The simulator picks an outage type, sometimes
makes the diagnosis uncertain, and tells the agent what each action did.

State (20 discrete values) = pattern (5) x search confidence (2) x attempt (2)
Actions (5)               = restart, rollback, scale, failover, escalate
"""

from __future__ import annotations

from dataclasses import dataclass, field

import gymnasium as gym
import numpy as np
from gymnasium import spaces

OUTAGE_TYPES = ["release", "db", "leak", "provider", "unknown"]
PATTERNS = ["recent release", "database overload", "memory climbing", "external timeouts", "unfamiliar pattern"]
ACTIONS = ["restart", "rollback", "scale", "failover", "escalate"]
ACTION_LABELS = {"restart": "Restart", "rollback": "Roll back", "scale": "Scale up", "failover": "Fail over",
                 "escalate": "Escalate to human"}
ACTION_MIN = {"restart": 3, "rollback": 5, "scale": 6, "failover": 2}
HUMAN_MIN = 25      # minutes for an on-call engineer to fix it
CLEANUP_MIN = 35    # extra minutes when an action makes things worse
DIAG_MIN = 2        # minutes for the agent to read alerts and diagnose
UNKNOWN_HARM_RATE = 0.3  # chance that acting on an unfamiliar outage makes it worse
N_STATES = len(PATTERNS) * 4
N_ACTIONS = len(ACTIONS)

# What each automatic action does for each known outage type: (fixes?, minutes, makes it worse?)
OUTCOMES = {
    "release": {"rollback": (1, 4, 0), "restart": (0, 3, 0), "scale": (0, 6, 0), "failover": (0, 2, 0)},
    "db": {"scale": (1, 6, 0), "restart": (0, 8, 1), "rollback": (0, 5, 0), "failover": (0, 2, 0)},
    "leak": {"restart": (1, 3, 0), "scale": (1, 9, 0), "rollback": (0, 5, 0), "failover": (0, 2, 0)},
    "provider": {"failover": (1, 2, 0), "restart": (0, 3, 0), "rollback": (0, 5, 0), "scale": (0, 6, 0)},
}


def state_index(pattern: int, confident: int, attempt: int) -> int:
    return pattern * 4 + confident * 2 + attempt


def action_outcome(outage_type: str, action: str, rng, diagnosis_right: bool = True) -> dict:
    """What one automatic action does to an outage.

    The single source of truth for action effects: training uses it, and so do the
    random outages in the live demo. `rng` is anything with a .random() method.
    """
    if not diagnosis_right:  # acted on the wrong service
        return {"fixed": False, "minutes": ACTION_MIN[action] + CLEANUP_MIN, "harm": True}
    if outage_type == "unknown":
        if rng.random() < UNKNOWN_HARM_RATE:
            return {"fixed": False, "minutes": ACTION_MIN[action] + CLEANUP_MIN, "harm": True}
        return {"fixed": False, "minutes": ACTION_MIN[action], "harm": False}
    fixed, minutes, harm = OUTCOMES[outage_type][action]
    return {"fixed": bool(fixed), "minutes": minutes + (CLEANUP_MIN if harm else 0), "harm": bool(harm)}


def reward_for(outcome: dict) -> float:
    """+20 when fixed, -0.5 per minute, -25 if the action made things worse."""
    if outcome["harm"]:
        return -25 - 0.5 * outcome["minutes"]
    if outcome["fixed"]:
        return 20 - 0.5 * outcome["minutes"]
    return -0.5 * outcome["minutes"]


@dataclass
class Outage:
    type: str
    pattern: int
    confident: int
    diagnosis_right: bool


@dataclass
class EpisodeLog:
    minutes: float = DIAG_MIN
    harm: bool = False
    human: bool = False
    fixed_alone: bool = False
    tried: set = field(default_factory=set)


class OutageEnv(gym.Env):
    """Gymnasium environment: one episode = one simulated outage."""

    metadata = {"render_modes": []}

    def __init__(self, uncertain_rate: float = 0.25):
        super().__init__()
        self.observation_space = spaces.Discrete(N_STATES)
        self.action_space = spaces.Discrete(N_ACTIONS)
        self.uncertain_rate = uncertain_rate
        self.outage: Outage | None = None
        self.attempt = 0
        self.log = EpisodeLog()

    # -- helpers -----------------------------------------------------------------
    def _sample_outage(self) -> Outage:
        r = self.np_random
        t = OUTAGE_TYPES[int(r.integers(len(OUTAGE_TYPES)))]
        # unfamiliar outages can be unclear too (e.g. two failures at once with unknown alerts)
        confident = int(r.random() >= self.uncertain_rate)
        right = True if confident else bool(r.random() < 0.5)
        return Outage(t, OUTAGE_TYPES.index(t), confident, right)

    def _outcome(self, action: str) -> dict:
        o = self.outage
        if action == "escalate":
            return {"fixed": True, "minutes": HUMAN_MIN, "harm": False, "human": True}
        return {**action_outcome(o.type, action, self.np_random, o.diagnosis_right), "human": False}

    def valid_actions(self) -> list[int]:
        """An automatic action is not repeated within one outage; escalating is always allowed."""
        return [i for i, a in enumerate(ACTIONS) if a == "escalate" or a not in self.log.tried]

    def observation(self) -> int:
        return state_index(self.outage.pattern, self.outage.confident, self.attempt)

    # -- gym API -----------------------------------------------------------------
    def reset(self, *, seed: int | None = None, options: dict | None = None):
        super().reset(seed=seed)
        self.outage = self._sample_outage()
        self.attempt = 0
        self.log = EpisodeLog()
        return self.observation(), {"type": self.outage.type}

    def step(self, action_index: int):
        action = ACTIONS[int(action_index)]
        out = self._outcome(action)
        reward = reward_for(out)
        self.log.minutes += out["minutes"]
        self.log.tried.add(action)
        done = out["fixed"] or out["harm"]
        if out["harm"]:
            self.log.harm = True
            self.log.minutes += HUMAN_MIN  # a human has to clean up
        if out.get("human"):
            self.log.human = True
        if out["fixed"] and not out.get("human"):
            self.log.fixed_alone = True
        if not done:
            if self.attempt == 1:  # two failed fixes: forced hand-over
                reward += 20 - 0.5 * HUMAN_MIN - 5
                self.log.minutes += HUMAN_MIN
                self.log.human = True
                done = True
            else:
                self.attempt = 1
        info = {"minutes": self.log.minutes, "harm": self.log.harm, "human": self.log.human,
                "fixed_alone": self.log.fixed_alone}
        return self.observation(), float(reward), done, False, info


def make_rng(seed: int) -> np.random.Generator:
    return np.random.default_rng(seed)
