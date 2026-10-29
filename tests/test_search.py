from app.scenarios import affected_services
from app.search import hypothesis_search, root_cause
from app.services import is_external


def _inputs(key):
    roots, ups = affected_services(key)
    alerting = [r for r in roots if not is_external(r)] + ups
    sick = set(alerting) | {r for r in roots if is_external(r)}
    return roots, alerting, sick


def test_astar_finds_single_root_cause():
    for key in ("release", "db", "leak", "cert"):
        roots, alerting, sick = _inputs(key)
        rc = root_cause(alerting, sick)
        assert rc["best"] == roots
        assert rc["confident"]


def test_astar_blames_external_provider_not_payment():
    roots, alerting, sick = _inputs("provider")
    rc = root_cause(alerting, sick)
    assert rc["best"] == ["provider"]
    assert not rc["stats"]["bfs_correct"]  # BFS stops at payment-svc


def test_two_failures_found_with_low_confidence():
    roots, alerting, sick = _inputs("double")
    rc = root_cause(alerting, sick)
    assert set(rc["best"]) == set(roots)
    assert not rc["confident"]


def test_astar_expands_fewer_than_bfs_on_double_failure():
    _, alerting, sick = _inputs("double")
    a = hypothesis_search(alerting, sick, "astar")
    b = hypothesis_search(alerting, sick, "bfs")
    assert a.expanded < b.expanded
