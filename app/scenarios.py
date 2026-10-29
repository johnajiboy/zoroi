"""Outage scenarios used for the live demo.

Each scenario is modelled on a common failure type from published industry
postmortems. The `outcomes` table says what each automatic action does in this
scenario: (fixes it?, minutes taken, makes it worse?).

A random outage picks 1 or 2 failed services from the service graph and gives each
one a failure mode that fits its kind, so every run is different.
"""

from __future__ import annotations

import random

from .services import CALLERS, NODES, is_external, upstream

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
    "config": {
        "name": "Bad config change", "hint": "Gateway routing change at 14:01", "roots": ["gateway"],
        "type": "release", "sev": "SEV-1",
        "root_alert": "config deploy api-gateway routes rev 318 completed 14:01:12; HTTP 502 41% since change",
        "outcomes": {"rollback": (1, 3, 0), "restart": (0, 3, 0), "scale": (0, 6, 0), "failover": (0, 2, 0)},
        "notes": {"rollback": "routes back to rev 317, 502s gone", "restart": "pods reload the same bad routes",
                  "scale": "more gateways, same bad routes", "failover": "backup region uses the same config"},
        "cause": "a bad routing rule in api-gateway config rev 318", "human": "reverts the config to rev 317",
        "suggest": "revert api-gateway config to rev 317",
        "follow": "check gateway config changes in staging before rollout",
        "learn": {"label": "Roll back the config change", "action": "rollback",
                  "keywords": ["roll back", "rollback", "revert", "previous config"], "minutes": 3},
    },
    "disk": {
        "name": "Queue disk full", "hint": "Event queue out of disk space", "roots": ["queue"], "type": "unknown",
        "sev": "SEV-2",
        "root_alert": "events-queue disk /data 100% full: no space left on device; producers rejected since 13:58",
        "outcomes": {"restart": (0, 4, 0), "rollback": (0, 5, 0), "scale": (0, 6, 0), "failover": (0, 2, 0)},
        "notes": {"restart": "broker came back with the disk still full", "rollback": "nothing recent to roll back",
                  "scale": "new broker added, existing partitions still full", "failover": "no standby queue"},
        "cause": "old events filling the events-queue disk",
        "human": "deletes expired event segments and lowers retention to 3 days",
        "suggest": "free disk on events-queue by lowering retention",
        "follow": "alert at 80% disk and cap events-queue retention by size",
        "learn": {"label": "Free disk space on the queue", "action": None,
                  "keywords": ["disk", "space", "retention", "purge", "segment"], "minutes": 5},
    },
    "dns": {
        "name": "Provider DNS failure", "hint": "Card provider address not resolving", "roots": ["provider"],
        "type": "provider", "sev": "SEV-1",
        "root_alert": "payment-svc DNS timeout resolving api.card-provider.com (SERVFAIL); upstream card-provider "
                      "unreachable",
        "outcomes": {"failover": (1, 2, 0), "restart": (0, 3, 0), "rollback": (0, 5, 0), "scale": (0, 6, 0)},
        "notes": {"failover": "payments flow through the backup provider's address",
                  "restart": "fresh pods hit the same DNS error", "rollback": "nothing recent to roll back",
                  "scale": "more servers, same DNS error"},
        "cause": "a DNS outage for the card provider's domain", "human": "fails over to the backup provider",
        "suggest": "fail over to the backup card provider",
        "follow": "cache provider DNS records and add a second resolver",
        "learn": {"label": "Fail over to the backup provider", "action": "failover",
                  "keywords": ["fail over", "failover", "backup"], "minutes": 2},
    },
    "spike": {
        "name": "Traffic spike", "hint": "Search flooded by crawler traffic", "roots": ["search"], "type": "unknown",
        "sev": "SEV-2",
        "root_alert": "search-svc requests 9,400/s (6x normal, 82% from one crawler), CPU 99%, request queue 4,800",
        "outcomes": {"restart": (0, 3, 1), "scale": (0, 6, 0), "rollback": (0, 5, 0), "failover": (0, 2, 0)},
        "notes": {"restart": "restarting halved capacity and search went fully down",
                  "scale": "new pods filled up within minutes", "rollback": "nothing recent to roll back",
                  "failover": "backup region got the same traffic"},
        "cause": "a traffic spike from one crawler overloading search-svc",
        "human": "rate-limits the crawler at the gateway", "suggest": "rate-limit the crawler at api-gateway",
        "follow": "add per-client rate limits on search",
        "learn": {"label": "Rate-limit the crawler", "action": None,
                  "keywords": ["rate limit", "rate-limit", "ratelimit", "throttl", "crawler", "bot"], "minutes": 4},
    },
}

RANDOM = "random"
ORDER = ["release", "config", "db", "disk", "leak", "provider", "dns", "spike", "double", "cert", RANDOM]

# -- random outages ----------------------------------------------------------------
# Failure modes a random outage can use. Each one is the generic form of a named
# scenario above; {svc} and the other fields are filled in when the outage is made.
# A mode only applies to the kind of service it makes sense for (see _modes_for).
_GENERIC_NOTES = {"rollback": "nothing recent to roll back", "failover": "no backup for {svc}"}
MODES: dict[str, dict] = {
    "release": {
        "name": "Bad release", "type": "release", "sev": "SEV-2",
        "alert": "deploy {svc} v2.{minor}.0 completed 14:0{mm}:{ss}; HTTP 5xx {pct}% since deploy",
        "outcomes": SCENARIOS["release"]["outcomes"],
        "notes": {"rollback": "errors back to normal", "restart": "errors return within a minute",
                  "scale": "more servers, same bug", "failover": "no backup for {svc}"},
        "cause": "a bug in {svc} v2.{minor}.0", "human": "rolls back {svc} to the previous version",
        "suggest": "roll back {svc} to the previous version", "follow": "add a canary stage for {svc} releases",
        "learn": SCENARIOS["release"]["learn"],
    },
    "config": {
        "name": "Bad config change", "type": "release", "sev": "SEV-2",
        "alert": "config deploy {svc} settings rev {rev} completed 14:0{mm}:{ss}; HTTP 502 {pct}% since change",
        "outcomes": SCENARIOS["config"]["outcomes"],
        "notes": {"rollback": "config back to the previous revision", "restart": "pods reload the same bad config",
                  "scale": "more servers, same bad config", "failover": "backup uses the same config"},
        "cause": "a bad setting in {svc} config rev {rev}", "human": "reverts the {svc} config change",
        "suggest": "revert the {svc} config to the previous revision",
        "follow": "check {svc} config changes in staging before rollout",
        "learn": SCENARIOS["config"]["learn"],
    },
    "leak": {
        "name": "Memory leak", "type": "leak", "sev": "SEV-3",
        "alert": "{svc} memory {mem}% of limit, GC pauses {gc}s, last deploy {days} days ago",
        "outcomes": SCENARIOS["leak"]["outcomes"],
        "notes": {"restart": "memory back to 40%", "scale": "extra pods hold it, leak remains", **_GENERIC_NOTES},
        "cause": "a memory leak in {svc}", "human": "restarts {svc} pods", "suggest": "restart {svc} pods",
        "follow": "alert at 80% memory and find the leak in {svc}",
        "learn": SCENARIOS["leak"]["learn"],
    },
    "spike": {
        "name": "Traffic spike", "type": "unknown", "sev": "SEV-2",
        "alert": "{svc} requests {rps},{rps3}00/s ({x}x normal, {bot}% from one crawler), CPU 99%",
        "outcomes": SCENARIOS["spike"]["outcomes"],
        "notes": {"restart": "restarting halved capacity and {svc} went fully down",
                  "scale": "new pods filled up within minutes", **_GENERIC_NOTES},
        "cause": "a traffic spike from one crawler overloading {svc}", "human": "rate-limits the crawler at the gateway",
        "suggest": "rate-limit the crawler at api-gateway", "follow": "add per-client rate limits on {svc}",
        "learn": SCENARIOS["spike"]["learn"],
    },
    "cert": {
        "name": "Expired certificate", "type": "unknown", "sev": "SEV-1",
        "alert": "{svc} TLS handshake failed: x509 certificate has expired",
        "outcomes": SCENARIOS["cert"]["outcomes"],
        "notes": {"restart": "same TLS error after restart", "rollback": "same error on the old version",
                  "scale": "new pods fail the same way", "failover": "backup uses the same certificate"},
        "cause": "an expired TLS certificate on {svc}", "human": "renews the certificate",
        "suggest": "renew the {svc} TLS certificate", "follow": "alert 30 days before certificates expire",
        "learn": SCENARIOS["cert"]["learn"],
    },
    "db": {
        "name": "Database overload", "type": "db", "sev": "SEV-1",
        "alert": "{svc} CPU {cpu}%, active connections {conn}/{conn}, query p95 {p95}s",
        "outcomes": SCENARIOS["db"]["outcomes"],
        "notes": {"scale": "read replica added, p95 back to normal",
                  "restart": "dropped every live connection; requests failed for 8 min", **_GENERIC_NOTES},
        "cause": "{svc} running out of connections", "human": "adds a read replica",
        "suggest": "add a read replica to {svc}", "follow": "autoscale {svc} connections",
        "learn": SCENARIOS["db"]["learn"],
    },
    "disk": {
        "name": "Disk full", "type": "unknown", "sev": "SEV-2",
        "alert": "{svc} disk /data 100% full: no space left on device; writes rejected",
        "outcomes": SCENARIOS["disk"]["outcomes"],
        "notes": {"restart": "came back with the disk still full", "scale": "new node added, old data still full",
                  **_GENERIC_NOTES},
        "cause": "old data filling the {svc} disk", "human": "deletes expired data and lowers retention",
        "suggest": "free disk on {svc} by lowering retention", "follow": "alert at 80% disk on {svc}",
        "learn": SCENARIOS["disk"]["learn"],
    },
    "cache": {
        "name": "Cache out of memory", "type": "leak", "sev": "SEV-2",
        "alert": "{svc} memory {mem}% of maxmemory, evictions failing, clients refused",
        "outcomes": {"restart": (1, 2, 0), "scale": (1, 7, 0), "rollback": (0, 5, 0), "failover": (0, 2, 0)},
        "notes": {"restart": "cache restarted empty and is warming up", "scale": "bigger cache node holds it",
                  "rollback": "nothing recent to roll back", "failover": "no cache replica"},
        "cause": "{svc} running out of memory", "human": "restarts {svc} and raises maxmemory",
        "suggest": "restart {svc}", "follow": "set an eviction policy on {svc}",
        "learn": {"label": "Restart the cache", "action": "restart", "keywords": ["restart", "reboot", "flush"],
                  "minutes": 2},
    },
    "provider": {
        "name": "Provider outage", "type": "provider", "sev": "SEV-1",
        "alert": "{caller} upstream {svc} timeouts after 30s (no internal errors)",
        "outcomes": SCENARIOS["provider"]["outcomes"], "notes": SCENARIOS["provider"]["notes"],
        "cause": "an outage at {svc}", "human": "fails over to the backup provider",
        "suggest": "fail over to the backup provider", "follow": "test failover monthly",
        "learn": SCENARIOS["provider"]["learn"],
    },
    "dns": {
        "name": "Provider DNS failure", "type": "provider", "sev": "SEV-1",
        "alert": "{caller} DNS timeout resolving api.{svc}.com (SERVFAIL); upstream {svc} unreachable",
        "outcomes": SCENARIOS["dns"]["outcomes"], "notes": SCENARIOS["dns"]["notes"],
        "cause": "a DNS outage for {svc}", "human": "fails over to the backup provider",
        "suggest": "fail over to the backup provider", "follow": "cache provider DNS records",
        "learn": SCENARIOS["dns"]["learn"],
    },
}
P_TWO_FAILURES = 0.3
FAILABLE = [n for n in NODES if n != "web"]  # same as the search experiment


def _modes_for(node: str) -> list[str]:
    """Failure modes that make sense for this kind of service."""
    svc, kind = NODES[node]["svc"], NODES[node]["kind"]
    if kind == "external":
        return ["provider", "dns"]
    if svc.endswith("-db"):
        return ["db", "disk"]
    if kind == "db":
        return ["cache"] if "cache" in svc else ["disk"]
    return ["release", "config", "leak", "spike", "cert"]


def _fill(value, fields: dict):
    """Format every string in a (nested) template with the outage's fields."""
    if isinstance(value, str):
        return value.format(**fields)
    if isinstance(value, dict):
        return {k: _fill(v, fields) for k, v in value.items()}
    return value


def _one_failure(node: str, mode: str, rng: random.Random) -> dict:
    callers = CALLERS[node]
    fields = {"svc": NODES[node]["svc"], "caller": NODES[callers[0]]["svc"] if callers else "",
              "minor": rng.randint(3, 19), "mm": rng.randint(0, 5), "ss": f"{rng.randint(0, 59):02d}",
              "pct": rng.randint(25, 60), "rev": rng.randint(200, 499), "mem": rng.randint(95, 99),
              "gc": f"{rng.uniform(1.2, 3.0):.1f}", "days": rng.randint(3, 12), "rps": rng.randint(4, 12),
              "rps3": rng.randint(0, 9), "x": rng.randint(4, 9), "bot": rng.randint(60, 90),
              "cpu": rng.randint(94, 99), "conn": rng.choice([200, 300, 500]), "p95": f"{rng.uniform(2, 6):.1f}"}
    m = MODES[mode]
    return {"node": node, "mode": mode, "name": m["name"], "type": m["type"], "sev": m["sev"],
            "root_alert": _fill(m["alert"], fields), "outcomes": m["outcomes"], "notes": _fill(m["notes"], fields),
            **{k: _fill(m[k], fields) for k in ("cause", "human", "suggest", "follow")}, "learn": m["learn"]}


def _independent(a: str, b: str) -> bool:
    """Two failures neither of which is a caller of the other, like the 'double' scenario."""
    return a not in upstream(b) and b not in upstream(a)


def random_scenario(rng: random.Random | None = None) -> dict:
    """Make a new outage: 1 or 2 random failed services, each with a failure mode that fits it.

    Returns a scenario dict with the same fields as the named ones, so the rest of the
    pipeline (alerts, search, decision, escalation, learning) treats it the same way.
    """
    rng = rng or random.Random()
    while True:
        roots = rng.sample(FAILABLE, 2 if rng.random() < P_TWO_FAILURES else 1)
        if len(roots) == 1 or _independent(*roots):
            break
    parts = [_one_failure(r, rng.choice(_modes_for(r)), rng) for r in roots]
    if len(parts) == 1:
        p = parts[0]
        mode = p["name"][0].lower() + p["name"][1:]  # keep acronyms like DNS
        return {"key": RANDOM, "name": f"Random: {mode} on {NODES[p['node']]['label']}",
                "hint": "", "roots": roots, **{k: p[k] for k in ("type", "sev", "root_alert", "outcomes", "notes",
                                                                 "cause", "human", "suggest", "follow", "learn")}}
    a, b = parts
    label_b = b["learn"]["label"]
    return {
        "key": RANDOM, "name": f"Random: {NODES[a['node']]['label']} and {NODES[b['node']]['label']} together",
        "hint": "", "roots": roots, "type": "double", "sev": "SEV-1",
        "root_alert": f"{a['root_alert']}; {b['root_alert']}",
        "root_alerts": {a["node"]: a["root_alert"], b["node"]: b["root_alert"]},
        "outcomes": {},  # one automatic action cannot fix two failures
        "harm_note": f"acted on one failure only; with {NODES[a['node']]['svc']} and {NODES[b['node']]['svc']} "
                     "both down, the outage spread",
        "notes": {}, "cause": f"{a['cause']} and {b['cause']} together", "human": f"{a['human']}, then {b['human']}",
        "suggest": f"{a['suggest']}, then {b['suggest']}", "follow": a["follow"],
        "learn": {"label": f"{a['learn']['label']}, then {label_b[0].lower()}{label_b[1:]}", "action": None,
                  "keywords": a["learn"]["keywords"] + b["learn"]["keywords"],
                  "minutes": a["learn"]["minutes"] + b["learn"]["minutes"]},
    }


def get_scenario(scenario: str | dict) -> dict:
    """Accept a scenario key or an already-built scenario (a random outage)."""
    return SCENARIOS[scenario] if isinstance(scenario, str) else scenario


# -- alerts and outcomes ------------------------------------------------------------
def affected_services(scenario: str | dict) -> tuple[list[str], list[str]]:
    """Return (roots, upstream services that degrade)."""
    roots = get_scenario(scenario)["roots"]
    ups: list[str] = []
    for r in roots:
        for u in upstream(r):
            if u not in ups and u not in roots:
                ups.append(u)
    return roots, ups


def build_alerts(scenario: str | dict, seed: int | None = None) -> list[dict]:
    """Raw alert lines as a monitoring tool would send them.

    An external service sends no alerts of its own, so its root alert comes from
    the first internal service that calls it.
    """
    rng = random.Random(seed)
    s = get_scenario(scenario)
    roots, ups = affected_services(s)
    texts = s.get("root_alerts") or {roots[0]: s["root_alert"]}
    alerts: list[dict] = []
    from_caller: dict[str, str] = {}
    for r in roots:
        text = texts.get(r, f"{NODES[r]['svc']} health check failing")
        if is_external(r):
            from_caller[CALLERS[r][0]] = text
        else:
            alerts.append({"service": r, "severity": "critical", "text": text})
    for u in ups:
        if u in from_caller:
            alerts.append({"service": u, "severity": "critical", "text": from_caller[u]})
        elif u in ("web", "gateway"):
            alerts.append({"service": u, "severity": "warning",
                           "text": f"{NODES[u]['svc']} HTTP 5xx {12 + rng.randint(0, 20)}% (threshold 5%)"})
        else:
            alerts.append({"service": u, "severity": "warning",
                           "text": f"{NODES[u]['svc']} p95 latency {2 + rng.random() * 3:.1f}s (threshold 0.8s)"})
    return alerts


def scenario_outcome(scenario: str | dict, action: str) -> dict:
    """What an automatic action does in this scenario."""
    s = get_scenario(scenario)
    if not s["outcomes"]:  # two failures at once: any single action makes it worse
        return {"fixed": False, "minutes": _ACTION_MIN[action] + CLEANUP_MIN, "harm": True, "note": s["harm_note"]}
    fixed, minutes, harm = s["outcomes"][action]
    return {"fixed": bool(fixed), "minutes": minutes + (CLEANUP_MIN if harm else 0), "harm": bool(harm),
            "note": s["notes"][action]}


_ACTION_MIN = {"restart": 3, "rollback": 5, "scale": 6, "failover": 2}
CLEANUP_MIN = 35


def scenario_list() -> list[dict]:
    out = []
    for k in ORDER:
        if k == RANDOM:
            out.append({"key": k, "name": "Random outage", "hint": "1 or 2 random services fail", "sev": "varies",
                        "clear": False})
            continue
        s = SCENARIOS[k]
        clear = s["type"] != "unknown" and len(s["roots"]) == 1
        out.append({"key": k, "name": s["name"], "hint": s["hint"], "sev": s["sev"], "clear": clear})
    return out
