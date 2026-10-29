from app.agent import BASELINES, QAgent, evaluate
from app.simulator import ACTIONS, PATTERNS, OutageEnv, state_index


def test_env_episode_terminates():
    env = OutageEnv()
    env.reset(seed=1)
    done, steps = False, 0
    while not done:
        _, _, done, _, info = env.step(ACTIONS.index("restart") if steps == 0 else ACTIONS.index("escalate"))
        steps += 1
    assert steps <= 2 and info["minutes"] > 0


def test_trained_agent_learns_when_to_escalate():
    agent = QAgent()
    agent.train(4000, seed=2026)
    all_actions = list(range(len(ACTIONS)))
    # clear, familiar cases: act
    assert ACTIONS[agent.greedy(state_index(PATTERNS.index("database overload"), 1, 0), all_actions)] == "scale"
    assert ACTIONS[agent.greedy(state_index(PATTERNS.index("recent release"), 1, 0), all_actions)] == "rollback"
    # uncertain or unfamiliar cases: escalate
    assert ACTIONS[agent.greedy(state_index(PATTERNS.index("database overload"), 0, 0), all_actions)] == "escalate"
    assert ACTIONS[agent.greedy(state_index(PATTERNS.index("unfamiliar pattern"), 1, 0), all_actions)] == "escalate"


def test_agent_beats_baselines():
    agent = QAgent()
    agent.train(4000, seed=2026)
    rl = evaluate(agent.policy(), 1000)
    act = evaluate(BASELINES["act"], 1000)
    rule = evaluate(BASELINES["rule"], 1000)
    assert rl["avg_recovery_min"] < act["avg_recovery_min"] < rule["avg_recovery_min"]
    assert rl["made_worse_pct"] < act["made_worse_pct"]
