# Zoroi

**Act or Escalate: an AI agent for cloud incident response using LLMs, A\* search and reinforcement learning.**

MSc Artificial Intelligence with Data Analytics, Teesside University
Module: CIS4049-N Artificial Intelligence Foundations
Author: John Oluwapelumi Ajiboye

---

## What it does

When an online service fails, one broken component sets off alerts across many services. Zoroi:

1. **Reads the alerts (LLM).** Turns raw alert text into structured facts: affected services, failure pattern, recent changes.
2. **Finds the root cause (A\* search).** Searches failure hypotheses on the service dependency graph for the explanation that accounts for every alert, and reports how confident it is.
3. **Decides to act or escalate (Q-learning).** Fixes clear, familiar problems itself (restart, roll back, scale up, fail over) and hands uncertain or unfamiliar ones to an engineer.
4. **Learns from engineers.** After an escalation, the engineer's fix is fed back. After three confirmed fixes for the same pattern, Zoroi handles it alone.
5. **Writes the incident report (LLM).**

The console streams every step live, with an animated agent flow, the service map, the agent's reasoning and the results.

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env             # optional: choose an LLM provider
uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000. On first start the agent trains on 4,000 simulated outages (about a second) and saves `models/qtable.json`.

The default LLM provider is `mock`, a deterministic rule-based reader, so everything runs offline. To use a real model, set `LLM_PROVIDER`, `LLM_MODEL` and the matching API key in `.env`, and `pip install anthropic` or `pip install openai`.

## Experiments

```bash
python -m experiments.train --episodes 4000 --seeds 5   # learning curve (CSV + PNG)
python -m experiments.evaluate --episodes 1000          # RL agent vs baselines
python -m experiments.compare_search --outages 200      # A* vs BFS vs greedy
pytest                                                  # tests
```

Results are written to `experiments/results/`.

## Project structure

```
app/
  main.py         FastAPI app: API endpoints, server-sent events, serves the console
  incident.py     Runs one incident through the pipeline and streams each step
  llm.py          LLM layer (mock, Anthropic or OpenAI) with schema validation
  search.py       A*, BFS and greedy search over failure hypotheses
  simulator.py    Gymnasium environment: one episode = one simulated outage
  agent.py        Q-learning agent, baseline policies, evaluation
  lessons.py      Learning from engineers' fixes (3 confirmations to act alone)
  scenarios.py    Six demo outages modelled on common postmortem failure types
  services.py     Service dependency graph
frontend/         Incident console (HTML, CSS, JavaScript; no build step)
experiments/      Training, evaluation and search comparison scripts
tests/            pytest suite
models/           Saved Q-table and lessons (generated)
```

## API

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/meta` | Scenarios, service graph, settings |
| GET | `/api/results` | Policy comparison on 1,000 simulated outages |
| POST | `/api/incidents` | Start an incident `{scenario, policy, speed}` |
| GET | `/api/incidents/{id}/events` | Live event stream (server-sent events) |
| POST | `/api/incidents/{id}/human` | Engineer's answer to an escalation |
| POST | `/api/incidents/{id}/speed` | Change playback speed |
| GET / DELETE | `/api/lessons` | View or reset what Zoroi learned from engineers |
| POST | `/api/train` | Retrain the agent `{episodes, seed}` |

## Limitations

- Services, outages and action outcomes are simulated. Results show that the method works, not exact real-world performance.
- The reward values shape how cautious the agent is. Sensitivity to them should be tested and reported.
- The mock LLM uses keyword rules. A real LLM is needed to evaluate extraction accuracy on real alert formats.
- In a real deployment, risky actions (rollbacks, failovers) should need human approval, and every action should be logged.
