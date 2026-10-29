from app.lessons import NEED_CONFIRMATIONS, LessonStore
from app.llm import mock_parse_alerts, mock_parse_note
from app.scenarios import build_alerts


def test_mock_llm_patterns():
    expected = {"release": "recent release", "db": "database overload", "leak": "memory climbing",
                "provider": "external timeouts", "double": "database overload", "cert": "unfamiliar pattern"}
    for key, pattern in expected.items():
        assert mock_parse_alerts(build_alerts(key, seed=1)).pattern == pattern


def test_note_parsing_prefers_scenario_fix():
    keywords = {"learn": ["cert", "renew"], "restart": ["restart"]}
    assert mock_parse_note("I renewed the expired cert", keywords) == "learn"
    assert mock_parse_note("just restarted it", keywords) == "restart"
    assert mock_parse_note("no idea", keywords) is None


def test_lesson_needs_confirmations(tmp_path):
    store = LessonStore(tmp_path / "lessons.json")
    key = "unfamiliar pattern|auth"
    for i in range(NEED_CONFIRMATIONS):
        assert not store.mastered(key)
        store.record(key, scenario="cert", label="Renew the certificate", action=None, worked=True, minutes=4)
    assert store.mastered(key)
    assert LessonStore(tmp_path / "lessons.json").mastered(key)  # persisted


def test_wrong_fix_is_not_learned(tmp_path):
    store = LessonStore(tmp_path / "lessons.json")
    lesson = store.record("k", scenario="cert", label="x", action=None, worked=False, minutes=4)
    assert lesson["ok"] == 0 and lesson["wrong"] == 1 and lesson["value"] < 0
