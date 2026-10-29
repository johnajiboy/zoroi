"""Service dependency graph for the simulated online shop.

Each service lists what it depends on. When a dependency fails, every service
upstream of it (the callers) degrades too. Coordinates are only used by the
front end to draw the map.
"""

from __future__ import annotations

from collections import deque

NODES: dict[str, dict] = {
    "web": {"label": "Web app", "svc": "web-frontend", "x": 80, "y": 260, "kind": "service"},
    "gateway": {"label": "API gateway", "svc": "api-gateway", "x": 230, "y": 260, "kind": "service"},
    "auth": {"label": "Auth", "svc": "auth-svc", "x": 400, "y": 70, "kind": "service"},
    "checkout": {"label": "Checkout", "svc": "checkout-svc", "x": 400, "y": 180, "kind": "service"},
    "cart": {"label": "Cart", "svc": "cart-svc", "x": 400, "y": 320, "kind": "service"},
    "search": {"label": "Search", "svc": "search-svc", "x": 400, "y": 440, "kind": "service"},
    "payment": {"label": "Payment", "svc": "payment-svc", "x": 580, "y": 100, "kind": "service"},
    "orders": {"label": "Orders", "svc": "orders-svc", "x": 580, "y": 230, "kind": "service"},
    "stock": {"label": "Stock", "svc": "stock-svc", "x": 580, "y": 350, "kind": "service"},
    "ordersdb": {"label": "Orders DB", "svc": "orders-db", "x": 760, "y": 130, "kind": "db"},
    "queue": {"label": "Event queue", "svc": "events-queue", "x": 760, "y": 250, "kind": "db"},
    "productdb": {"label": "Product DB", "svc": "product-db", "x": 760, "y": 370, "kind": "db"},
    "cache": {"label": "Cache", "svc": "redis-cache", "x": 760, "y": 470, "kind": "db"},
    "provider": {"label": "Card provider", "svc": "card-provider", "x": 890, "y": 50, "kind": "external"},
    "notif": {"label": "Notifications", "svc": "notify-svc", "x": 890, "y": 330, "kind": "service"},
}

# (caller, dependency)
DEPS: list[tuple[str, str]] = [
    ("web", "gateway"), ("gateway", "auth"), ("gateway", "checkout"), ("gateway", "cart"),
    ("gateway", "search"), ("checkout", "payment"), ("checkout", "orders"), ("checkout", "stock"),
    ("cart", "stock"), ("cart", "cache"), ("search", "productdb"), ("search", "cache"),
    ("payment", "provider"), ("payment", "ordersdb"), ("orders", "ordersdb"), ("orders", "queue"),
    ("stock", "productdb"), ("notif", "queue"),
]

CALLERS: dict[str, list[str]] = {k: [] for k in NODES}
DEPENDENCIES: dict[str, list[str]] = {k: [] for k in NODES}
for _caller, _dep in DEPS:
    DEPENDENCIES[_caller].append(_dep)
    CALLERS[_dep].append(_caller)


def is_external(node: str) -> bool:
    return NODES[node]["kind"] == "external"


def upstream(node: str) -> list[str]:
    """All services that (directly or indirectly) call `node`, in BFS order."""
    out: list[str] = []
    seen = {node}
    queue = deque([node])
    while queue:
        n = queue.popleft()
        for caller in CALLERS[n]:
            if caller not in seen:
                seen.add(caller)
                out.append(caller)
                queue.append(caller)
    return out


def graph_payload() -> dict:
    """Graph data for the front end."""
    return {
        "nodes": [{"id": k, **v} for k, v in NODES.items()],
        "deps": [list(d) for d in DEPS],
    }
