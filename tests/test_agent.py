from app.agent import BASELINES, QAgent, evaluate
from app.simulator import ACTIONS, N_STATES, PATTERNS, OutageEnv, state_index


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


def test_unfamiliar_low_confidence_outage_escalates():
    agent = QAgent()
    agent.train(4000, seed=2026)
    s = state_index(PATTERNS.index("unfamiliar pattern"), 0, 0)
    assert agent.visits[s] > 0  # covered by training, not only by the safety rule
    assert ACTIONS[agent.greedy(s, list(range(len(ACTIONS))))] == "escalate"
    # every first-attempt state is now seen in training
    assert all(agent.visits[state_index(p, c, 0)] > 0 for p in range(len(PATTERNS)) for c in (0, 1))


def test_state_with_zero_visits_escalates(tmp_path):
    agent = QAgent()
    s = state_index(PATTERNS.index("recent release"), 1, 0)
    agent.q[s, ACTIONS.index("rollback")] = 10.0
    all_actions = list(range(len(ACTIONS)))
    assert agent.unseen(s) and ACTIONS[agent.greedy(s, all_actions)] == "escalate"
    agent.visits[s] = 1
    assert ACTIONS[agent.greedy(s, all_actions)] == "rollback"
    # visit counts are saved with the Q-table
    agent.save(tmp_path / "q.json")
    loaded = QAgent.load(tmp_path / "q.json")
    assert loaded.visits[s] == 1 and loaded.visits.shape == (N_STATES,)


def test_reward_values_are_env_parameters():
    from app.simulator import HARM_PENALTY, HUMAN_MIN, reward_for
    env = OutageEnv()
    assert (env.harm_penalty, env.human_min) == (HARM_PENALTY, HUMAN_MIN) == (25, 25)
    harm = {"fixed": False, "minutes": 10, "harm": True}
    assert reward_for(harm) == -30 and reward_for(harm, 50) == -55
    env = OutageEnv(human_min=40)
    env.reset(seed=1)
    _, reward, done, _, info = env.step(ACTIONS.index("escalate"))
    assert done and reward == 0 and info["minutes"] == 2 + 40


def test_sensitivity_script_runs(tmp_path):
    from experiments import sensitivity
    rows = sensitivity.main(["--episodes", "200", "--seeds", "2", "--eval-episodes", "50", "--out", str(tmp_path)])
    assert len(rows) == 6 and sum(r["default"] for r in rows) == 2
    assert (tmp_path / "reward_sensitivity.csv").exists()
    assert {"avg_recovery_min_mean", "made_worse_pct_std", "escalated_pct_mean"} <= set(rows[0])
