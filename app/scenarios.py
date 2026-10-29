"""Outage scenarios used for the live demo.

Each scenario is modelled on a common failure type from published industry
postmortems. The `outcomes` table says what each automatic action does in this
scenario: (fixes it?, minutes taken, makes it worse?).
"""

from __future__ import annotations

import random

from .services import NODES, is_external, upstream

SCENARIOS: dict[str, dict] = {
    "release": {
        "name": "Bad release", "hint": "Checkout update at 14:02", "roots": ["checkout"], "type": "release",
        "sev": "SEV-2",
        "root_alert": "deploy checkout-svc v2.14.0 completed 14:02:41; HTTP 5xx 38% since deploy",
        "outcomes": {"rollback": (1, 4, 0), "restart": (0, 3, 0), "scale": (0, 6, 0), "failover": (0, 2, 0)},
        "notes": {"rollback": "errors back to 0.2%", "restart": "errors return within a minute",
                  "scale": "more servers, same bug", "failover": "no backup for checkout"},
        "cause": "a bug in checkout-svc v2.14.0", "human": "rolls back to v2.13.4",
        "suggest": "roll back checkout-svc to v2.13.4", "follow": "add a canary stage for checkout releases",
        "learn": {"label": "Roll back the release", "action": "rollback",
                  "keywords": ["roll back", "rollback", "revert", "previous version"], "minutes": 4},
    },
    "db": {
        "name": "Database overload", "hint": "Orders DB at its connection limit", "roots": ["ordersdb"], "type": "db",
        "sev": "SEV-1",
        "root_alert": "orders-db CPU 98%, active connections 500/500, query p95 4.2s",
        "outcomes": {"scale": (1, 6, 0), "restart": (0, 8, 1), "rollback": (0, 5, 0), "failover": (0, 2, 0)},
        "notes": {"scale": "read replica added, p95 back to 120 ms",
                  "restart": "dropped 500 live connections; payments failed for 8 min",
                  "rollback": "nothing recent to roll back", "failover": "no standby configured"},
        "cause": "orders-db running out of connections", "human": "adds a read replica",
        "suggest": "add a read replica to orders-db", "follow": "autoscale orders-db connections",
        "learn": {"label": "Add a read replica", "action": "scale",
                  "keywords": ["replica", "scale", "capacity"], "minutes": 6},
    },
    "leak": {
        "name": "Memory leak", "hint": "Stock service filling memory", "roots": ["stock"], "type": "leak",
        "sev": "SEV-3",
        "root_alert": "stock-svc memory 97% of limit, GC pauses 2.1s, last deploy 6 days ago",
        "outcomes": {"restart": (1, 3, 0), "scale": (1, 9, 0), "rollback": (0, 5, 0), "failover": (0, 2, 0)},
        "notes": {"restart": "memory back to 41%", "scale": "extra pods hold it, leak remains",
                  "rollback": "no recent change", "failover": "no backup for stock"},
        "cause": "a memory leak in stock-svc", "human": "restarts stock-svc pods",
        "suggest": "restart stock-svc pods", "follow": "alert at 80% memory and find the leak",
        "learn": {"label": "Restart the pods", "action": "restart",
                  "keywords": ["restart", "reboot"], "minutes": 3},
    },
    "provider": {
        "name": "Card provider down", "hint": "External partner not answering", "roots": ["provider"],
        "type": "provider", "sev": "SEV-1",
        "root_alert": "payment-svc upstream card-provider timeouts after 30s (no internal errors)",
        "outcomes": {"failover": (1, 2, 0), "restart": (0, 3, 0), "rollback": (0, 5, 0), "scale": (0, 6, 0)},
        "notes": {"failover": "payments flow through backup provider", "restart": "provider still down",
                  "rollback": "nothing recent to roll back", "scale": "more servers, same timeouts"},
        "cause": "an outage at the external card provider", "human": "fails over to the backup provider",
        "suggest": "fail over to the backup card provider", "follow": "test failover monthly",
        "learn": {"label": "Fail over to the backup provider", "action": "failover",
                  "keywords": ["fail over", "failover", "backup"], "minutes": 2},
    },
    "double": {
        "name": "Two failures at once", "hint": "Cache and Product DB together", "roots": ["productdb", "cache"],
        "type": "db", "sev": "SEV-1",
        "root_alert": "product-db CPU 96%, slow queries; redis-cache connection refused",
        "outcomes": {},  # any single automatic action makes it worse
        "harm_note": "acted on product-db only; with the cache down too, Search went fully offline",
        "notes": {},
        "cause": "product-db overload and a redis-cache crash together",
        "human": "restores the cache, then scales product-db",
        "suggest": "restore redis-cache first, then scale product-db",
        "follow": "block database restarts while the cache is down",
        "learn": {"label": "Restore the cache, then scale product-db", "action": None,
                  "keywords": ["cache", "redis"], "minutes": 7},
    },
    "cert": {
        "name": "Unfamiliar error", "hint": "Auth fails, never seen before", "roots": ["auth"], "type": "unknown",
        "sev": "SEV-1",
        "root_alert": "auth-svc TLS handshake failed: x509 certificate has expired",
        "outcomes": {"restart": (0, 3, 0), "rollback": (0, 5, 0), "scale": (0, 6, 0), "failover": (0, 2, 0)},
        "notes": {"restart": "same TLS error after restart", "rollback": "same error on the old version",
                  "scale": "new pods fail the same way", "failover": "backup uses the same certificate"},
        "cause": "an expired TLS certificate on auth-svc", "human": "renews the certificate",
        "suggest": "renew the auth-svc TLS certificate", "follow": "alert 30 days before certificates expire",
        "learn": {"label": "Renew the certificate", "action": None,
                  "keywords": ["cert", "renew", "expired", "tls"], "minutes": 4},
    },
}

ORDER = ["release", "db", "leak", "provider", "double", "cert"]


def affected_services(key: str) -> tuple[list[str], list[str]]:
    """Return (roots, upstream services that degrade)."""
    roots = SCENARIOS[key]["roots"]
    ups: list[str] = []
    for r in roots:
        for u in upstream(r):
            if u not in ups and u not in roots:
                ups.append(u)
    return roots, ups


def build_alerts(key: str, seed: int | None = None) -> list[dict]:
    """Raw alert lines as a monitoring tool would send them."""
    rng = random.Random(seed)
    s = SCENARIOS[key]
    roots, ups = affected_services(key)
    alerts: list[dict] = []
    if not any(is_external(r) for r in roots):
        alerts.append({"service": roots[0], "severity": "critical", "text": s["root_alert"]})
        for extra in roots[1:]:
            alerts.append({"service": extra, "severity": "critical", "text": f"{NODES[extra]['svc']} health check failing"})
    for i, u in enumerate(ups):
        if any(is_external(r) for r in roots) and i == 0:
            alerts.append({"service": u, "severity": "critical", "text": s["root_alert"]})
        elif u in ("web", "gateway"):
            alerts.append({"service": u, "severity": "warning",
                           "text": f"{NODES[u]['svc']} HTTP 5xx {12 + rng.randint(0, 20)}% (threshold 5%)"})
        else:
            alerts.append({"service": u, "severity": "warning",
                           "text": f"{NODES[u]['svc']} p95 latency {2 + rng.random() * 3:.1f}s (threshold 0.8s)"})
    return alerts


def scenario_outcome(key: str, action: str) -> dict:
    """What an automatic action does in this scenario."""
    s = SCENARIOS[key]
    if key == "double":
        return {"fixed": False, "minutes": _ACTION_MIN[action] + CLEANUP_MIN, "harm": True, "note": s["harm_note"]}
    fixed, minutes, harm = s["outcomes"][action]
    return {"fixed": bool(fixed), "minutes": minutes + (CLEANUP_MIN if harm else 0), "harm": bool(harm),
            "note": s["notes"][action]}


_ACTION_MIN = {"restart": 3, "rollback": 5, "scale": 6, "failover": 2}
CLEANUP_MIN = 35


def scenario_list() -> list[dict]:
    out = []
    for k in ORDER:
        s = SCENARIOS[k]
        clear = s["type"] != "unknown" and k != "double"
        out.append({"key": k, "name": s["name"], "hint": s["hint"], "sev": s["sev"], "clear": clear})
    return out
