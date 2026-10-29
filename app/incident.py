"""Runs one incident through the full pipeline and streams each step as an event.

Alerts -> LLM reads them -> A* finds the root cause -> RL decides to act or escalate
-> (engineer fixes it and Zoroi learns) -> recovery -> LLM writes the report.

Events are pushed onto an asyncio.Queue and streamed to the browser with
server-sent events. Pauses between steps are for the live demo only.
"""

from __future__ import annotations

import asyncio
import random
import uuid
from dataclasses import dataclass, field

import numpy as np

from .agent import BASELINES, QAgent
from .lessons import NEED_CONFIRMATIONS, LessonStore
from .llm import LLMClient, action_keywords
from .scenarios import RANDOM, SCENARIOS, affected_services, build_alerts, random_scenario, scenario_outcome
from .search import root_cause
from .services import NODES, is_external
from .simulator import ACTION_LABELS, ACTIONS, DIAG_MIN, HUMAN_MIN, PATTERNS, state_index

HUMAN_Q_ALPHA = 0.3


@dataclass
class Context:
    agent: QAgent
    lessons: LessonStore
    llm: LLMClient
    save_agent: callable = None


@dataclass
class IncidentRunner:
    scenario: str
    policy: str
    speed: float
    ctx: Context
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    clock: float = 0.0
    _human: asyncio.Future | None = None
    task: asyncio.Task | None = None
    spec: dict = field(init=False)

    def __post_init__(self) -> None:
        # a random outage is generated once here, so every step sees the same one
        self.spec = random_scenario() if self.scenario == RANDOM else SCENARIOS[self.scenario]

    # -- plumbing ----------------------------------------------------------------
    async def emit(self, type_: str, **data) -> None:
        await self.queue.put({"type": type_, "clock": round(self.clock), **data})

    async def pause(self, ms: float) -> None:
        await asyncio.sleep(ms / 1000 / max(self.speed, 0.1))

    def answer(self, response: dict) -> bool:
        if self._human and not self._human.done():
            self._human.set_result(response)
            return True
        return False

    def start(self) -> None:
        self.task = asyncio.create_task(self._run_safe())

    async def _run_safe(self) -> None:
        try:
            await self.run()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - surface errors to the UI
            await self.emit("error", message=str(exc))
        finally:
            await self.queue.put({"type": "end"})

    # -- the pipeline ------------------------------------------------------------
    async def run(self) -> None:
        k, s, ctx = self.scenario, self.spec, self.ctx
        roots, ups = affected_services(s)
        number = 4101 + list(SCENARIOS).index(k) if k in SCENARIOS else random.randint(4200, 4999)
        await self.emit("start", incident=f"INC-{number}", scenario=k, name=s["name"], sev=s["sev"])

        # 1. failure spreads and alerts fire
        alerts = build_alerts(s, seed=hash(self.id) % 10_000)
        by_service = {a["service"]: a for a in alerts}
        for r in roots:
            await self.emit("health", service=r, status="bad", alert=by_service.get(r, {}).get("text"))
        for u in ups:
            await self.pause(260)
            self.clock += 9
            await self.emit("health", service=u, status="bad" if by_service[u]["severity"] == "critical" else "warn",
                            alert=by_service[u]["text"])
        alerting = [r for r in roots if not is_external(r)] + ups
        await self.emit("alerts_done", count=len(alerts) * 3)

        # 2. LLM reads the alerts
        await self.emit("llm_start", count=len(alerts) * 3)
        await self.pause(1300)
        summary = await asyncio.to_thread(ctx.llm.parse_alerts, alerts)
        self.clock += 20
        await self.emit("llm_result", summary=summary.model_dump(), provider=ctx.llm.provider)

        # 3. A* search for the root cause
        sick = set(alerting) | {r for r in roots if is_external(r)}
        rc = root_cause(alerting, sick)
        await self.emit("search_start")
        for n in rc["pool"]:
            await self.pause(150)
            await self.emit("search_visit", service=n)
        self.clock += 25
        marked = rc["best"] if len(rc["best"]) > 1 or rc["confident"] or len(rc["candidates"]) < 2 \
            else rc["best"] + rc["candidates"][1]["services"][:1]
        await self.emit("search_result", **rc, marked=marked)

        # 4. decide: act or escalate
        pattern = PATTERNS.index(summary.pattern)
        conf = int(rc["confident"])
        lesson_key = f"{summary.pattern}|{'+'.join(sorted(rc['best']))}"
        target = NODES[rc["best"][0]]["svc"]
        learn = s["learn"]
        rng = np.random.default_rng(random.randrange(10**6))
        total, harm, human, fixed_by = DIAG_MIN, False, False, None
        tried: set[str] = set()
        attempt = 0
        while True:
            st = state_index(pattern, conf, attempt)
            valid = [i for i, a in enumerate(ACTIONS) if a == "escalate" or a not in tried]
            if self.policy == "rl" and attempt == 0 and ctx.lessons.mastered(lesson_key):
                action = "learned"
            elif self.policy == "rl":
                action = ACTIONS[ctx.agent.greedy(st, valid)]
            else:
                action = ACTIONS[BASELINES[self.policy](st, valid, rng)]
            await self.emit("decide_start", attempt=attempt)
            await self.pause(1100)
            await self.emit("decision", **self._decision_payload(st, action, lesson_key, attempt))

            if action == "escalate":
                mins, learned = await self._escalate(lesson_key, pattern, "unfamiliar" if conf else "unclear")
                total += mins
                human = True
                break

            lesson = ctx.lessons.get(lesson_key) if action == "learned" else None
            label = lesson["label"] if lesson else ACTION_LABELS[action]
            await self.emit("act_start", action=action, label=label, target=target)
            await self.pause(1300)
            if lesson and lesson["label"] == learn["label"]:
                out = {"fixed": True, "harm": False, "minutes": learn["minutes"],
                       "note": f"Used the fix engineers confirmed {lesson['ok']} times"}
            elif lesson:  # same pattern and service, but a different cause (possible with random outages)
                out = {"fixed": False, "harm": False, "minutes": learn["minutes"],
                       "note": "this outage has a different cause from the one the fix was learned on"}
            else:
                out = scenario_outcome(s, action)
            tried.add(action)
            self.clock += out["minutes"] * 60
            total += out["minutes"]
            await self.emit("act_result", action=action, label=label, **out)
            if out["harm"]:
                harm = True
                await self.pause(900)
                mins, _ = await self._escalate(lesson_key, pattern, "cleanup")
                total += mins
                human = True
                break
            if out["fixed"]:
                fixed_by = label
                break
            await self.pause(500)
            if attempt == 1:
                mins, _ = await self._escalate(lesson_key, pattern, "forced")
                total += mins
                human = True
                break
            attempt = 1

        # 5. recovery and report
        await self.emit("recovering", source="escalate" if human else "act")
        for n in roots + ups:
            await self.emit("health", service=n, status="info")
        await self.pause(700)
        for n in roots + ups:
            await self.pause(110)
            await self.emit("health", service=n, status="ok")
        await self.pause(500)
        await self.emit("resolved", total=total, harm=harm, human=human)
        facts = {"services_affected": len(alerting), "cause": s["cause"], "human": human, "harm": harm,
                 "human_fix": s["human"], "action_label": fixed_by or "", "minutes": total,
                 "follow_up": s["follow"]}
        report = await asyncio.to_thread(ctx.llm.write_report, facts)
        await self.emit("report", text=report)

    # -- helpers -----------------------------------------------------------------
    def _decision_payload(self, st: int, action: str, lesson_key: str, attempt: int) -> dict:
        ctx = self.ctx
        rows = [{"action": a, "label": ACTION_LABELS[a], "value": round(float(ctx.agent.q[st, i]), 2)}
                for i, a in enumerate(ACTIONS)]
        lesson = ctx.lessons.get(lesson_key)
        note = None
        if lesson and lesson["ok"]:
            rows.append({"action": "learned", "label": lesson["label"], "value": lesson["value"]})
            note = ("mastered" if lesson["ok"] >= NEED_CONFIRMATIONS else "partial")
        rows.sort(key=lambda r: -r["value"])
        return {
            "action": action, "label": lesson["label"] if action == "learned" else ACTION_LABELS[action],
            "policy": self.policy, "q_values": rows if self.policy == "rl" else [], "attempt": attempt,
            "lesson": {"ok": lesson["ok"], "need": NEED_CONFIRMATIONS, "state": note} if lesson and lesson["ok"] else None,
        }

    async def _escalate(self, lesson_key: str, pattern: int, reason: str) -> tuple[float, bool]:
        ctx, s, learn = self.ctx, self.spec, self.spec["learn"]
        lesson = ctx.lessons.get(lesson_key)
        learn_value = learn["action"] or "learn"
        options = [{"value": a, "label": lbl} for a, lbl in
                   [("restart", "Restarted the service"), ("rollback", "Rolled back"), ("scale", "Scaled up"),
                    ("failover", "Failed over")] if a != learn["action"]]
        options.append({"value": learn_value, "label": learn["label"]})
        suggested = learn["label"] if lesson and lesson["ok"] else s["suggest"]
        reasons = {
            "unfamiliar": "This pattern is unfamiliar, so acting alone is too risky.",
            "unclear": "The cause is unclear, and acting now could make the outage worse.",
            "cleanup": "The automatic action made the outage worse. A human needs to clean up and fix it.",
            "forced": "Two automatic fixes did not work, so the agent is handing over.",
        }
        self._human = asyncio.get_running_loop().create_future()
        await self.emit("escalate", reason=reasons[reason], kind=reason, evidence=s["root_alert"], cause=s["cause"],
                        suggested=suggested, learned_from=lesson["ok"] if lesson and lesson["ok"] else 0,
                        options=options)
        resp = await self._human
        choice, note_reading = resp.get("choice"), None
        if resp.get("how") == "approve":
            choice = learn_value
        elif not choice and resp.get("note"):
            # the scenario's own fix is checked first, then the generic actions
            keywords = {learn_value: learn["keywords"],
                        **{k: v for k, v in action_keywords().items() if k != learn_value}}
            option_labels = {o["value"]: o["label"] for o in options}
            choice = await asyncio.to_thread(ctx.llm.parse_note, resp["note"], option_labels, keywords)
            note_reading = {"note": resp["note"], "understood_as": option_labels.get(choice)}
        right = choice == learn_value
        label = next((o["label"] for o in options if o["value"] == choice), None)
        minutes = HUMAN_MIN + (10 if choice and not right else 0)
        self.clock += minutes * 60
        await self.emit("human_result", how=resp.get("how"), choice=choice, label=label, worked=right,
                        minutes=minutes, note_reading=note_reading, human_fix=s["human"], learn_label=learn["label"])
        if choice:
            await self.emit("learning_start")
            await self.pause(1300)
            # random outages have no fixed key, so their lessons are listed by outage name
            new = ctx.lessons.record(lesson_key, scenario=s["name"] if self.scenario == RANDOM else self.scenario,
                                     label=learn["label"], action=learn["action"], worked=right,
                                     minutes=learn["minutes"])
            if right and learn["action"]:  # known action: also update the Q-table directly
                a = ACTIONS.index(learn["action"])
                reward = 20 - 0.5 * learn["minutes"]
                for c in (0, 1):
                    s_idx = state_index(pattern, c, 0)
                    ctx.agent.q[s_idx, a] += HUMAN_Q_ALPHA * (reward - ctx.agent.q[s_idx, a])
                if ctx.save_agent:
                    ctx.save_agent()
            await self.emit("learning_result", lesson=new, worked=right, label=label, need=NEED_CONFIRMATIONS,
                            pattern=s["name"])
        return minutes, right
