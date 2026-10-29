# CLAUDE.md

Guidance for AI coding assistants working in this repository.

## Project

Zoroi is an MSc AI Foundations (CIS4049-N) project: an incident response agent that combines
an LLM (reads alerts, reads engineers' notes, writes reports), A* search (root cause over failure
hypotheses) and Q-learning (decide to act or escalate). It also learns from engineers' fixes
after escalations. FastAPI backend, plain HTML/CSS/JS front end with no build step.

The assessment marks the AI techniques: their selection, justification, implementation and
experimental validation. Keep changes focused on that. The UI exists to demonstrate the agent.

## Commands

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload            # run the console at http://127.0.0.1:8000
pytest                                   # run all tests
python -m experiments.train --seeds 5    # learning curve
python -m experiments.evaluate           # RL agent vs baselines
python -m experiments.compare_search     # A* vs BFS vs greedy
```

## Architecture

- `app/incident.py` is the pipeline. It emits events (`start`, `health`, `llm_result`,
  `search_result`, `decision`, `act_result`, `escalate`, `human_result`, `learning_result`,
  `resolved`, `report`, `end`) onto a queue that `app/main.py` streams as server-sent events.
- `frontend/app.js` only renders events. All decisions are made in Python. Never move agent
  logic into the front end.
- `app/simulator.py` is the Gymnasium environment used for training. State index =
  pattern (5) x search confidence (2) x attempt (2) = 20 states; 5 actions.
- `app/search.py`: A* with an admissible heuristic (unexplained alerts / max alerts one service
  explains). BFS and greedy exist as baselines; keep all three working.
- `app/lessons.py`: a learned fix needs `NEED_CONFIRMATIONS` (3) successful human fixes before
  the agent acts on it alone.
- `app/llm.py`: providers `mock` (default), `anthropic`, `openai`. Every LLM output is validated
  with Pydantic and falls back to the mock rules if invalid. The LLM never triggers actions.

## Conventions

- Python 3.11+, type hints, small functions, docstrings that explain why.
- Keep the mock LLM provider working so the project runs offline and tests need no API key.
- When changing rewards, search costs or scenarios, re-run `pytest` and the experiments, and
  update the README if results change.
- Front end: dark theme only, colours from the CSS custom properties in `frontend/styles.css`.
  Keep the agent-flow animation (particles along edges, node halos) intact.
- Plain, simple English in UI text and docs. No emoji in code or docs.

## Git

- The repository owner is the sole author. Do not add `Co-Authored-By` trailers, "Generated
  with" lines, or any AI attribution to commits, pull requests, code comments or documents.
- Use short, imperative commit messages (e.g. "Add BFS baseline to search comparison").
- Never commit `.env` or files in `models/` and `experiments/results/`.
