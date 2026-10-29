"""Learning from engineers' fixes after an escalation.

Each outage pattern (LLM pattern + root cause found by search) gets a lesson.
A fix that worked raises its learned value and confirmation count. Zoroi only
acts alone on a learned fix after NEED_CONFIRMATIONS successful human fixes.
"""

from __future__ import annotations

import json
from pathlib import Path
from threading import Lock

NEED_CONFIRMATIONS = 3
LESSON_ALPHA = 0.5


class LessonStore:
    def __init__(self, path: Path):
        self.path = path
        self._lock = Lock()
        self.lessons: dict[str, dict] = {}
        if path.exists():
            self.lessons = json.loads(path.read_text())

    def get(self, key: str) -> dict | None:
        return self.lessons.get(key)

    def mastered(self, key: str) -> bool:
        lesson = self.lessons.get(key)
        return bool(lesson and lesson["ok"] >= NEED_CONFIRMATIONS)

    def record(self, key: str, *, scenario: str, label: str, action: str | None, worked: bool,
               minutes: float) -> dict:
        with self._lock:
            lesson = self.lessons.setdefault(
                key, {"scenario": scenario, "label": label, "action": action, "ok": 0, "wrong": 0, "value": 0.0})
            if worked:
                lesson["ok"] += 1
                lesson["label"], lesson["action"] = label, action
                reward = 20 - 0.5 * minutes
                lesson["value"] += LESSON_ALPHA * (reward - lesson["value"])
            else:
                lesson["wrong"] += 1
                lesson["value"] += LESSON_ALPHA * (-10 - lesson["value"])
            lesson["value"] = round(lesson["value"], 2)
            self._save()
            return dict(lesson)

    def clear(self) -> None:
        with self._lock:
            self.lessons = {}
            self._save()

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.lessons, indent=1))

    def payload(self) -> list[dict]:
        return [{"key": k, **v, "mastered": v["ok"] >= NEED_CONFIRMATIONS} for k, v in self.lessons.items()]
