"""LLM layer: reads alerts, reads engineers' notes, writes incident reports.

Providers (set LLM_PROVIDER in .env):
  mock      - deterministic keyword rules, no API key needed (default)
  anthropic - Anthropic Messages API (needs ANTHROPIC_API_KEY, LLM_MODEL)
  openai    - OpenAI Chat Completions API (needs OPENAI_API_KEY, LLM_MODEL)

Every LLM answer is validated against a Pydantic schema. If the model returns
invalid output twice, the mock rules are used instead, so the agent never acts
on malformed data.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from .services import NODES
from .simulator import ACTION_LABELS, PATTERNS

log = logging.getLogger("zoroi.llm")

Pattern = Literal["recent release", "database overload", "memory climbing", "external timeouts",
                  "unfamiliar pattern"]


class AlertSummary(BaseModel):
    affected_services: list[str] = Field(description="Service names that are alerting")
    pattern: Pattern
    recent_change: bool
    external_dependency: bool
    summary: str = Field(max_length=300)


class NoteReading(BaseModel):
    action: str | None = Field(description="One of the option keys, or null if unclear")


ALERT_SYSTEM = (
    "You are the alert-reading step of an incident response agent. Read the raw monitoring alerts and "
    "return ONLY a JSON object with keys: affected_services (list of service names), pattern (one of: "
    + ", ".join(PATTERNS)
    + "), recent_change (bool), external_dependency (bool), summary (one plain sentence). "
    "Use 'unfamiliar pattern' when the alerts do not clearly match another pattern. No markdown."
)
NOTE_SYSTEM = (
    "An on-call engineer wrote a short note about how they fixed an outage. Choose which option key best "
    "matches what they did. Return ONLY JSON: {\"action\": \"<key>\"} or {\"action\": null} if unclear."
)
REPORT_SYSTEM = (
    "Write a short incident report (3 sentences max) in plain English for engineers: what failed, what "
    "fixed it and how long it took, and one follow-up action. No headings, no markdown."
)


class LLMClient:
    def __init__(self, provider: str | None = None, model: str | None = None):
        self.provider = (provider or os.getenv("LLM_PROVIDER", "mock")).lower()
        self.model = model or os.getenv("LLM_MODEL", "")
        self._client = None
        if self.provider == "anthropic":
            import anthropic  # lazy import: optional dependency
            self._client = anthropic.Anthropic()
        elif self.provider == "openai":
            import openai
            self._client = openai.OpenAI()
        elif self.provider != "mock":
            raise ValueError(f"Unknown LLM_PROVIDER: {self.provider}")
        if self.provider != "mock" and not self.model:
            raise ValueError("Set LLM_MODEL in .env when using a real LLM provider")

    # -- public API ----------------------------------------------------------------
    def parse_alerts(self, alerts: list[dict]) -> AlertSummary:
        text = "\n".join(f"[{a['severity']}] {a['text']}" for a in alerts)
        if self.provider == "mock":
            return mock_parse_alerts(alerts)
        return self._structured(ALERT_SYSTEM, text, AlertSummary, fallback=lambda: mock_parse_alerts(alerts))

    def parse_note(self, note: str, options: dict[str, str], keywords: dict[str, list[str]]) -> str | None:
        if self.provider == "mock":
            return mock_parse_note(note, keywords)
        prompt = f"Options: {json.dumps(options)}\nEngineer note: {note}"
        result = self._structured(NOTE_SYSTEM, prompt, NoteReading,
                                  fallback=lambda: NoteReading(action=mock_parse_note(note, keywords)))
        return result.action if result.action in options else None

    def write_report(self, facts: dict) -> str:
        if self.provider == "mock":
            return mock_report(facts)
        try:
            return self._complete(REPORT_SYSTEM, json.dumps(facts)).strip()
        except Exception as exc:  # noqa: BLE001 - report writing must never break the incident
            log.warning("Report generation failed, using template: %s", exc)
            return mock_report(facts)

    # -- provider calls ------------------------------------------------------------
    def _complete(self, system: str, user: str) -> str:
        if self.provider == "anthropic":
            msg = self._client.messages.create(model=self.model, max_tokens=500, system=system,
                                               messages=[{"role": "user", "content": user}])
            return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
        resp = self._client.chat.completions.create(
            model=self.model, messages=[{"role": "system", "content": system}, {"role": "user", "content": user}])
        return resp.choices[0].message.content or ""

    def _structured(self, system: str, user: str, schema: type[BaseModel], fallback):
        for attempt in range(2):
            try:
                raw = self._complete(system, user)
                raw = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.M).strip()
                return schema.model_validate_json(raw)
            except (ValidationError, json.JSONDecodeError, ValueError) as exc:
                log.warning("LLM output failed validation (attempt %d): %s", attempt + 1, exc)
            except Exception as exc:  # noqa: BLE001 - network or API error
                log.warning("LLM call failed: %s", exc)
                break
        return fallback()


# -- mock rules (also the fallback when a real LLM misbehaves) ---------------------
def mock_parse_alerts(alerts: list[dict]) -> AlertSummary:
    text = " ".join(a["text"].lower() for a in alerts)
    recent_deploy = "deploy" in text and "completed" in text
    if "memory" in text:
        pattern = "memory climbing"
    elif recent_deploy:
        pattern = "recent release"
    elif "timeout" in text and ("upstream" in text or "provider" in text):
        pattern = "external timeouts"
    elif "-db" in text and ("cpu" in text or "connections" in text):
        pattern = "database overload"
    else:
        pattern = "unfamiliar pattern"
    services = []
    for a in alerts:
        name = NODES[a["service"]]["svc"] if a.get("service") in NODES else a["text"].split()[0]
        if name not in services:
            services.append(name)
    return AlertSummary(
        affected_services=services, pattern=pattern, recent_change=recent_deploy,
        external_dependency="provider" in text or "upstream" in text,
        summary=f"{len(alerts)} alerts across {len(services)} services; pattern looks like {pattern}.",
    )


def mock_parse_note(note: str, keywords: dict[str, list[str]]) -> str | None:
    t = note.lower()
    for key, words in keywords.items():
        if any(w in t for w in words):
            return key
    return None


def mock_report(f: dict) -> str:
    who = ("An engineer " + ("cleaned up and " if f.get("harm") else "") + f["human_fix"] + "."
           if f.get("human") else f"Zoroi fixed it alone ({f.get('action_label', '')}).")
    return (f"{f['services_affected']} services degraded because of {f['cause']}. {who} "
            f"Recovered in {f['minutes']} min. Follow-up: {f['follow_up']}.")


def action_keywords() -> dict[str, list[str]]:
    return {"restart": ["restart", "reboot"], "rollback": ["roll back", "rollback", "revert"],
            "scale": ["scale", "replica", "capacity"], "failover": ["fail over", "failover", "backup"]}


__all__ = ["LLMClient", "AlertSummary", "ACTION_LABELS", "action_keywords"]
