"""API tests against a real uvicorn server (server-sent events need a live server)."""

import json
import socket
import threading
import time

import httpx
import pytest
import uvicorn

from app.main import app


@pytest.fixture(scope="module")
def base_url():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            httpx.get(url + "/api/meta", timeout=1)
            break
        except httpx.HTTPError:
            time.sleep(0.1)
    yield url
    server.should_exit = True
    thread.join(timeout=5)


def _run(base_url, scenario, on_escalate=None):
    iid = httpx.post(f"{base_url}/api/incidents", json={"scenario": scenario, "policy": "rl", "speed": 8}).json()["id"]
    events = []
    with httpx.stream("GET", f"{base_url}/api/incidents/{iid}/events", timeout=30) as r:
        for line in r.iter_lines():
            if not line.startswith("data: "):
                continue
            ev = json.loads(line[6:])
            events.append(ev)
            if ev["type"] == "escalate" and on_escalate:
                on_escalate(iid, ev)
            if ev["type"] == "end":
                break
    return events


def test_meta_and_results(base_url):
    meta = httpx.get(f"{base_url}/api/meta").json()
    assert len(meta["scenarios"]) == 6
    res = httpx.get(f"{base_url}/api/results").json()
    assert res["rl"]["avg_recovery_min"] < res["rule"]["avg_recovery_min"]


def test_clear_incident_is_fixed_alone(base_url):
    events = _run(base_url, "db")
    assert "escalate" not in [e["type"] for e in events]
    resolved = next(e for e in events if e["type"] == "resolved")
    assert not resolved["human"] and not resolved["harm"]


def test_unfamiliar_incident_escalates_and_learns(base_url):
    httpx.delete(f"{base_url}/api/lessons")

    def approve(iid, _ev):
        httpx.post(f"{base_url}/api/incidents/{iid}/human", json={"how": "approve"})

    for expected_ok in (1, 2, 3):
        events = _run(base_url, "cert", approve)
        learned = next(e for e in events if e["type"] == "learning_result")
        assert learned["worked"] and learned["lesson"]["ok"] == expected_ok

    # after three confirmations Zoroi fixes it alone
    events = _run(base_url, "cert")
    assert "escalate" not in [e["type"] for e in events]
    assert next(e for e in events if e["type"] == "decision")["action"] == "learned"
    httpx.delete(f"{base_url}/api/lessons")
