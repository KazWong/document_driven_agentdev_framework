"""Canonical dependency queries and bounded static projections."""

from __future__ import annotations

from collections import defaultdict, deque
from html import escape
from typing import Any, Iterable

from .common import FrameworkError
from .store import Store


def topological(nodes: Iterable[str], edges: Iterable[tuple[str, str]]) -> list[str]:
    nodes = set(nodes)
    indegree = {n: 0 for n in nodes}
    children: dict[str, list[str]] = defaultdict(list)
    for source, target in set(edges):
        if source not in nodes or target not in nodes:
            raise FrameworkError(f"missing dependency node: {source} -> {target}")
        children[source].append(target)
        indegree[target] += 1
    ready = deque(sorted(n for n, degree in indegree.items() if degree == 0))
    ordered = []
    while ready:
        current = ready.popleft()
        ordered.append(current)
        for child in sorted(children[current]):
            indegree[child] -= 1
            if indegree[child] == 0:
                ready.append(child)
    if len(ordered) != len(nodes):
        raise FrameworkError("dependency graph contains a cycle")
    return ordered


def graph_data(
    store: Store,
    *,
    focus: str | None = None,
    view: str = "overview",
    limit: int = 100,
    baseline: str | None = None,
) -> dict[str, Any]:
    if not 1 <= limit <= 2000:
        raise FrameworkError("graph view limit must be 1..2000")
    kinds = {
        "overview": None,
        "active": None,
        "requirements": {
            "requirement",
            "component",
            "interface",
            "verification_obligation",
        },
        "architecture": {"requirement", "component", "interface", "blueprint"},
        "verification": {
            "verification_obligation",
            "test_case",
            "suite",
            "candidate",
            "verification_result",
            "acceptance",
        },
        "work": {"work", "package", "plan", "candidate", "review"},
        "environment": {
            "environment",
            "provider",
            "environment_binding",
            "verification_result",
        },
        "approval": {"package", "approval", "role_output", "acceptance", "promotion"},
        "failure": None,
    }
    if view not in kinds:
        raise FrameworkError("unknown graph view")
    if baseline:
        records = store.history(baseline)
        rows = {
            r["id"]: {
                "id": r["id"],
                "kind": r["kind"],
                "owner": r["owner"],
                "revision": r["revision"],
                "state": "CURRENT",
                "cause": None,
            }
            for r in records
        }
        edges = [
            (d["reference"]["id"], r["id"], d["relation"])
            for r in records
            for d in r["dependencies"]
        ]
    else:
        rows = {r["id"]: r for r in store.list()}
        edges = [
            tuple(r)
            for r in store.db.execute(
                "SELECT upstream,downstream,relation FROM edges ORDER BY upstream,downstream,relation"
            )
        ]
    selected = {
        n for n, r in rows.items() if kinds[view] is None or r["kind"] in kinds[view]
    }
    if view == "failure":
        failed = (
            {
                r["id"]
                for r in records
                if (
                    isinstance(r["payload"], dict)
                    and (
                        (
                            isinstance(r["payload"].get("result"), dict)
                            and r["payload"]["result"].get("status", "passed")
                            != "passed"
                        )
                        or r["payload"].get("state")
                        in {"BLOCKED", "DIAGNOSING", "REPLAN_REQUIRED"}
                    )
                )
            }
            if baseline
            else {
                r[0]
                for r in store.db.execute(
                    "SELECT r.id FROM records r JOIN heads h USING(id,revision) WHERE json_extract(r.data,'$.payload.result.status') NOT IN ('passed') OR json_extract(r.data,'$.payload.state') IN ('BLOCKED','DIAGNOSING','REPLAN_REQUIRED')"
                )
            }
        )
        selected = {n for n in selected if rows[n]["state"] != "CURRENT" or n in failed}
        # Include causal ancestors rather than only the failed endpoint.
        parents: dict[str, list[str]] = defaultdict(list)
        for a, b, _ in edges:
            parents[b].append(a)
        q = deque(selected)
        while q:
            for parent in parents[q.popleft()]:
                if parent not in selected:
                    selected.add(parent)
                    q.append(parent)
    if focus:
        if focus not in rows:
            raise FrameworkError(f"unknown graph focus: {focus}")
        neighbors: dict[str, list[str]] = defaultdict(list)
        for a, b, _ in edges:
            neighbors[a].append(b)
            neighbors[b].append(a)
        chosen = {focus}
        q = deque([focus])
        while q and len(chosen) < limit:
            for n in sorted(neighbors[q.popleft()]):
                if n in selected and n not in chosen and len(chosen) < limit:
                    chosen.add(n)
                    q.append(n)
        selected &= chosen
        selected.add(focus)
    ordered = topological(
        rows, [(a, b) for a, b, _ in edges if a in rows and b in rows]
    )
    visible = [x for x in ordered if x in selected][:limit]
    visible_set = set(visible)
    historical = {r["id"]: r["payload"] for r in records} if baseline else {}
    for n in visible:
        payload = historical[n] if baseline else store.get(n)["payload"]
        state = rows[n]["state"]
        if state == "CURRENT" and isinstance(payload, dict):
            result = payload.get("result", {})
            if isinstance(result, dict) and result.get("status"):
                state = (
                    "CURRENT"
                    if result["status"] == "passed"
                    else ("FAILED" if result.get("candidate_evaluated") else "BLOCKED")
                )
            elif rows[n]["kind"] == "work":
                state = (
                    "BLOCKED"
                    if payload.get("state")
                    in {"BLOCKED", "DIAGNOSING", "REPLAN_REQUIRED"}
                    else (
                        "UNVERIFIED"
                        if payload.get("state")
                        in {"DRAFT", "IMPLEMENTING", "CANDIDATE"}
                        else "CURRENT"
                    )
                )
        rows[n] = {**rows[n], "validity": rows[n]["state"], "state": state}
    # Omitted count includes the rest of the alive project, not archived history.
    return {
        "view": view,
        "baseline": baseline,
        "focus": focus,
        "nodes": [rows[n] for n in visible],
        "edges": [
            {"upstream": a, "downstream": b, "relation": rel}
            for a, b, rel in edges
            if a in visible_set and b in visible_set
        ],
        "total_active": len(rows),
        "shown": len(visible),
        "omitted": len(rows) - len(visible),
    }


def explain(store: Store, artifact_id: str) -> dict[str, Any]:
    h = store.head(artifact_id)
    if h["state"] == "CURRENT":
        return {"id": artifact_id, "state": "CURRENT", "owner": h["owner"], "path": []}
    causes = set((h["cause"] or "").split(","))
    q = deque([(artifact_id, [artifact_id])])
    seen = {artifact_id}
    while q:
        node, path = q.popleft()
        if node in causes:
            return {
                "id": artifact_id,
                "state": h["state"],
                "owner": h["owner"],
                "path": list(reversed(path)),
                "action": "owner reevaluation required",
            }
        for r in store.db.execute(
            "SELECT upstream FROM edges WHERE downstream=? ORDER BY upstream", (node,)
        ):
            if r[0] not in seen:
                seen.add(r[0])
                q.append((r[0], path + [r[0]]))
    return {
        "id": artifact_id,
        "state": h["state"],
        "owner": h["owner"],
        "path": [artifact_id],
        "cause": h["cause"],
    }


def mermaid(data: dict[str, Any]) -> str:
    names = {n["id"]: f"n{i}" for i, n in enumerate(data["nodes"])}
    lines = ["flowchart TD"]
    for n in data["nodes"]:
        # Use numeric entity escapes for the small Mermaid-sensitive alphabet.
        label = f"{n['id']} r{n['revision']} — {n['state']}".replace('"', "#quot;")
        lines.append(f'  {names[n["id"]]}["{label}"]')
    for e in data["edges"]:
        lines.append(
            f"  {names[e['upstream']]} -->|{e['relation']}| {names[e['downstream']]}"
        )
    lines.append(
        f"  %% Shown {data['shown']}; omitted {data['omitted']}; projection only"
    )
    return "\n".join(lines) + "\n"


def svg(data: dict[str, Any]) -> str:
    """Deterministic layered SVG without scripts, links or external resources."""
    node_map = {n["id"]: n for n in data["nodes"]}
    rank: dict[str, int] = {}
    parent_ranks: dict[str, list[str]] = defaultdict(list)
    for e in data["edges"]:
        parent_ranks[e["downstream"]].append(e["upstream"])
    for n in data["nodes"]:
        rank[n["id"]] = max(
            (rank.get(p, 0) + 1 for p in parent_ranks[n["id"]]), default=0
        )
    levels: dict[int, list[str]] = defaultdict(list)
    for n, r in rank.items():
        levels[r].append(n)
    positions = {}
    row = 0
    for level in sorted(levels):
        for i, name in enumerate(levels[level]):
            positions[name] = (30 + (i % 5) * 250, 90 + (row + i // 5) * 105)
        row += (len(levels[level]) + 4) // 5
    height = max(230, 160 + row * 105)
    width = 1290
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img">',
        "<title>Artifact dependency graph</title>",
        '<rect width="100%" height="100%" fill="#101824"/>',
        '<defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto"><path d="M0,0 L0,6 L7,3 z" fill="#809bb9"/></marker></defs>',
        f'<text x="30" y="33" font-family="sans-serif" font-size="21" fill="#fff">{escape(data["view"].title())} · {data["shown"]} shown · {data["omitted"]} omitted</text>',
        '<text x="30" y="58" font-family="sans-serif" font-size="12" fill="#a5b5c9">Prerequisite → dependent. Green: CURRENT · Amber: STALE · Red: INVALID. Use a focused query for omitted nodes.</text>',
    ]
    for e in data["edges"]:
        x1, y1 = positions[e["upstream"]]
        x2, y2 = positions[e["downstream"]]
        out.append(
            f'<path d="M{x1+110},{y1+65} C{x1+110},{y1+85} {x2+110},{y2-20} {x2+110},{y2}" stroke="#809bb9" fill="none" marker-end="url(#arrow)"/>'
        )
    colors = {
        "CURRENT": "#1d5c49",
        "STALE": "#855e19",
        "INVALID": "#8a333d",
        "FAILED": "#8a333d",
        "BLOCKED": "#794c80",
        "UNVERIFIED": "#315574",
        "SUPERSEDED": "#475166",
    }
    for name, (x, y) in positions.items():
        n = node_map[name]
        color = colors.get(n["state"], "#475166")
        out.append(
            f'<g><rect x="{x}" y="{y}" width="225" height="65" rx="8" fill="{color}" stroke="#aec1d6"/><title>{escape(name)}</title>'
        )
        label = name if len(name) <= 28 else name[:25] + "…"
        out.append(
            f'<text x="{x+10}" y="{y+24}" font-family="monospace" font-size="12" fill="#fff">{escape(label)}</text>'
        )
        out.append(
            f'<text x="{x+10}" y="{y+46}" font-family="sans-serif" font-size="11" fill="#e6eff8">r{n["revision"]} · {escape(n["state"])} · {escape(n["owner"])}</text></g>'
        )
    out.append("</svg>")
    return "\n".join(out)
