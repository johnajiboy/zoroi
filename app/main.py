"""FastAPI app: serves the incident console and streams incidents to it."""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .agent import BASELINES, POLICY_NAMES, QAgent, evaluate
from .incident import Context, IncidentRunner
from .lessons import NEED_CONFIRMATIONS, LessonStore
from .llm import LLMClient
from .scenarios import SCENARIOS, scenario_list
from .services import graph_payload

ROOT = Path(__file__).resolve().parent.parent
MODELS = ROOT / "models"
QTABLE = MODELS / "qtable.json"
FRONTEND = ROOT / "frontend"
TRAIN_EPISODES = 4000

load_dotenv(ROOT / ".env")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("zoroi")

state: dict = {}


def _evaluate_all(agent: QAgent) -> dict:
    results = {"rl": evaluate(agent.policy())}
    for key in ("act", "rule", "escalate", "random"):
        results[key] = evaluate(BASELINES[key])
    return {k: {"name": POLICY_NAMES[k], **v} for k, v in results.items()}


@asynccontextmanager
async def lifespan(_: FastAPI):
    if QTABLE.exists():
        agent = QAgent.load(QTABLE)
        log.info("Loaded Q-table from %s", QTABLE)
    else:
        agent = QAgent()
        curve = agent.train(TRAIN_EPISODES)
        agent.save(QTABLE)
        log.info("Trained agent on %d simulated outages (final avg reward %.1f)", TRAIN_EPISODES,
                 curve[-1]["avg_reward"])
    state["agent"] = agent
    state["results"] = _evaluate_all(agent)
    state["lessons"] = LessonStore(MODELS / "lessons.json")
    state["llm"] = LLMClient()
    state["incidents"] = {}
    log.info("LLM provider: %s", state["llm"].provider)
    yield


app = FastAPI(title="Zoroi", description="Act-or-escalate incident response agent", lifespan=lifespan)


def _ctx() -> Context:
    return Context(agent=state["agent"], lessons=state["lessons"], llm=state["llm"],
                   save_agent=lambda: state["agent"].save(QTABLE))


# -- models ---------------------------------------------------------------------
class StartIncident(BaseModel):
    scenario: str
    policy: str = "rl"
    speed: float = Field(1.0, ge=0.25, le=8)


class HumanResponse(BaseModel):
    how: str = Field(pattern="^(approve|take)$")
    choice: str | None = None
    note: str | None = Field(None, max_length=500)


class SpeedChange(BaseModel):
    speed: float = Field(ge=0.25, le=8)


class TrainRequest(BaseModel):
    episodes: int = Field(TRAIN_EPISODES, ge=100, le=50_000)
    seed: int = 2026


# -- API ------------------------------------------------------------------------
@app.get("/api/meta")
def meta():
    return {"scenarios": scenario_list(), "graph": graph_payload(), "need": NEED_CONFIRMATIONS,
            "policies": {k: POLICY_NAMES[k] for k in ("rl", "act", "rule")},
            "llm_provider": state["llm"].provider, "train_episodes": TRAIN_EPISODES}


@app.get("/api/results")
def results():
    return state["results"]


@app.get("/api/lessons")
def lessons():
    return {"need": NEED_CONFIRMATIONS, "lessons": state["lessons"].payload()}


@app.delete("/api/lessons")
def clear_lessons():
    state["lessons"].clear()
    return {"ok": True}


@app.post("/api/train")
def train(req: TrainRequest):
    agent = QAgent()
    curve = agent.train(req.episodes, seed=req.seed)
    agent.save(QTABLE)
    state["agent"] = agent
    state["results"] = _evaluate_all(agent)
    return {"curve": curve, "results": state["results"]}


@app.post("/api/incidents")
async def start_incident(req: StartIncident):
    if req.scenario not in SCENARIOS:
        raise HTTPException(404, "Unknown scenario")
    if req.policy not in ("rl", *BASELINES):
        raise HTTPException(400, "Unknown policy")
    runner = IncidentRunner(req.scenario, req.policy, req.speed, _ctx())
    state["incidents"][runner.id] = runner
    runner.start()
    return {"id": runner.id}


@app.get("/api/incidents/{incident_id}/events")
async def incident_events(incident_id: str):
    runner: IncidentRunner | None = state["incidents"].get(incident_id)
    if not runner:
        raise HTTPException(404, "Unknown incident")

    async def stream():
        try:
            while True:
                event = await runner.queue.get()
                yield f"data: {json.dumps(event)}\n\n"
                if event["type"] == "end":
                    break
        except asyncio.CancelledError:  # browser closed the page
            if runner.task:
                runner.task.cancel()
            raise
        finally:
            state["incidents"].pop(incident_id, None)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/incidents/{incident_id}/human")
def human_response(incident_id: str, resp: HumanResponse):
    runner = state["incidents"].get(incident_id)
    if not runner or not runner.answer(resp.model_dump()):
        raise HTTPException(409, "This incident is not waiting for an engineer")
    return {"ok": True}


@app.post("/api/incidents/{incident_id}/speed")
def change_speed(incident_id: str, req: SpeedChange):
    runner = state["incidents"].get(incident_id)
    if runner:
        runner.speed = req.speed
    return {"ok": True}


# the console itself (mounted last so /api routes win)
app.mount("/", StaticFiles(directory=FRONTEND, html=True), name="frontend")
