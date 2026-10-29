import asyncio
import random

from app.agent import QAgent
from app.incident import Context, IncidentRunner
from app.lessons import NEED_CONFIRMATIONS, LessonStore
from app.llm import LLMClient, mock_parse_alerts
from app.scenarios import (FAILABLE, MODES, ORDER, RANDOM, SCENARIOS, _modes_for, build_alerts, random_scenario,
                           scenario_list, scenario_outcome)
from app.search import root_cause
from app.services import NODES, is_external, upstream
from app.simulator import ACTION_MIN, ACTIONS, CLEANUP_MIN, OUTCOMES, UNKNOWN_HARM_RATE

AUTO_ACTIONS = [a for a in ACTIONS if a != "escalate"]
PATTERN_OF_TYPE = {"release": "recent release", "db": "database overload", "leak": "memory climbing",
                   "provider": "external timeouts", "unknown": "unfamiliar pattern"}


def _search(spec):
    roots = spec["roots"]
    alerting = [r for r in roots if not is_external(r)] + [u for r in roots for u in upstream(r) if u not in roots]
    alerting = list(dict.fromkeys(alerting))
    return root_cause(alerting, set(alerting) | {r for r in roots if is_external(r)})


def test_every_scenario_is_complete():
    for key, s in SCENARIOS.items():
        for field in ("name", "hint", "roots", "type", "sev", "root_alert", "cause", "human", "suggest", "follow"):
            assert s[field], (key, field)
        assert {"label", "action", "keywords", "minutes"} <= set(s["learn"])
        if len(s["roots"]) == 1:
            assert set(s["outcomes"]) == set(AUTO_ACTIONS) == set(s["notes"]), key
    assert [s["key"] for s in scenario_list()] == ORDER and set(ORDER) == set(SCENARIOS) | {RANDOM}


def test_new_scenarios_reward_the_right_fix():
    fixed_by = {"config": {"rollback"}, "dns": {"failover"}, "disk": set(), "spike": set()}
    for key, fixes in fixed_by.items():
        assert {a for a in AUTO_ACTIONS if scenario_outcome(key, a)["fixed"]} == fixes, key
    # restarting under a traffic spike cuts capacity and makes it worse
    assert scenario_outcome("spike", "restart")["harm"]


def test_unfamiliar_scenarios_never_teach_a_generic_action():
    # learning a generic action here would update the Q-table for every unfamiliar outage
    for s in [*SCENARIOS.values(), *MODES.values()]:
        if s["type"] == "unknown":
            assert s["learn"]["action"] is None


def test_random_outage_is_reproducible_and_varied():
    assert random_scenario(random.Random(5)) == random_scenario(random.Random(5))
    rng = random.Random(1)
    outages = [random_scenario(rng) for _ in range(300)]
    assert {len(o["roots"]) for o in outages} == {1, 2}
    assert len({o["name"] for o in outages}) > 30
    for o in outages:
        assert o["key"] == RANDOM and all(r in FAILABLE for r in o["roots"])
        if len(o["roots"]) == 2:
            a, b = o["roots"]
            assert a not in upstream(b) and b not in upstream(a)
            assert scenario_outcome(o, "restart")["harm"]


def test_random_outage_alerts_match_its_failure_mode():
    rng = random.Random(2)
    for _ in range(300):
        o = random_scenario(rng)
        alerts = build_alerts(o, seed=1)
        critical = [a for a in alerts if a["severity"] == "critical"]
        assert len(critical) == len(o["roots"])  # one root alert per failure
        if len(o["roots"]) == 1:
            assert mock_parse_alerts(alerts).pattern == PATTERN_OF_TYPE[o["type"]]
            assert _search(o)["best"] == o["roots"]
            fixes = [a for a in AUTO_ACTIONS if scenario_outcome(o, a)["fixed"]]
            assert bool(fixes) == (o["type"] != "unknown")  # familiar types have an automatic fix


def test_every_failable_service_has_a_mode():
    for node in FAILABLE:
        modes = _modes_for(node)
        assert modes and all(m in MODES for m in modes), NODES[node]["svc"]


def _run_runner(runner: IncidentRunner) -> list[dict]:
    async def go():
        runner.start()
        events = []
        while True:
            ev = await runner.queue.get()
            events.append(ev)
            if ev["type"] == "escalate":
                runner.answer({"how": "approve"})
            if ev["type"] == "end":
                return events
    return asyncio.run(go())


def test_learned_fix_only_works_for_the_cause_it_was_learned_on(tmp_path):
    lessons = LessonStore(tmp_path / "lessons.json")
    cert = SCENARIOS["cert"]
    for _ in range(NEED_CONFIRMATIONS):
        lessons.record("unfamiliar pattern|auth", scenario="cert", label=cert["learn"]["label"], action=None,
                       worked=True, minutes=4)
    ctx = Context(agent=QAgent(), lessons=lessons, llm=LLMClient("mock"))

    same = IncidentRunner("cert", "rl", 8, ctx)
    act = next(e for e in _run_runner(same) if e["type"] == "act_result")
    assert act["action"] == "learned" and act["fixed"]

    # same pattern on the same service, but a different cause: the learned fix does not apply
    other = IncidentRunner("cert", "rl", 8, ctx)
    other.spec = {**cert, "learn": {**cert["learn"], "label": "Something else"}}
    act = next(e for e in _run_runner(other) if e["type"] == "act_result")
    assert act["action"] == "learned" and not act["fixed"]


def test_random_outages_use_the_simulator_outcomes():
    assert all("outcomes" not in m for m in MODES.values())  # no separate tables to drift
    rng = random.Random(9)
    unknown_harm = unknown_runs = 0
    for _ in range(400):
        o = random_scenario(rng)
        for a in AUTO_ACTIONS:
            out = scenario_outcome(o, a, rng)
            if o["type"] == "double":  # treated as a wrong diagnosis
                assert out["harm"] and out["minutes"] == ACTION_MIN[a] + CLEANUP_MIN
            elif o["type"] == "unknown":
                assert not out["fixed"] and out["minutes"] == ACTION_MIN[a] + (CLEANUP_MIN if out["harm"] else 0)
                unknown_runs += 1
                unknown_harm += out["harm"]
            else:
                fixed, minutes, harm = OUTCOMES[o["type"]][a]
                assert (out["fixed"], out["harm"]) == (bool(fixed), bool(harm))
                assert out["minutes"] == minutes + (CLEANUP_MIN if harm else 0)
    assert abs(unknown_harm / unknown_runs - UNKNOWN_HARM_RATE) < 0.06


def test_unseen_state_shows_in_the_decision_event(tmp_path):
    # an untrained agent has seen no states, so the safety rule makes it escalate
    ctx = Context(agent=QAgent(), lessons=LessonStore(tmp_path / "lessons.json"), llm=LLMClient("mock"))
    decision = next(e for e in _run_runner(IncidentRunner("release", "rl", 8, ctx)) if e["type"] == "decision")
    assert decision["action"] == "escalate" and decision["unseen"]
