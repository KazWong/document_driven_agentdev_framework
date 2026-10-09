#!/usr/bin/env python3
"""Measured graph/history scenarios with independent reachability oracles."""
import argparse
from collections import defaultdict, deque
from pathlib import Path
import resource
import statistics
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agent_framework.common import bytes_digest, write_json
from agent_framework.graph import graph_data, svg
from agent_framework.store import Store


def measured(call):
    start = time.perf_counter()
    value = call()
    return value, time.perf_counter() - start


def graph_case(root, size):
    children = defaultdict(set)
    edges = 0
    with Store(root / f"graph-{size}") as store:
        started = time.perf_counter()
        with store.transaction():
            for index in range(size):
                key = f"NODE-{index:08d}"
                parents = set()
                if index >= 10:
                    parents.add((index - 10) // 3)
                    if index % 5 == 0:
                        parents.add((index - 10) // 4)
                for parent in parents:
                    children[f"NODE-{parent:08d}"].add(key)
                edges += len(parents)
                store.publish(
                    key,
                    "component",
                    "framework",
                    {"index": index},
                    [(f"NODE-{p:08d}", "derived_from") for p in sorted(parents)],
                )
        build = time.perf_counter() - started
        expected = {"NODE-00000000"}
        q = deque(expected)
        while q:
            for child in children[q.popleft()]:
                if child not in expected:
                    expected.add(child)
                    q.append(child)
        reached, query = measured(
            lambda: set(store.descendants(["NODE-00000000"], include_roots=True))
        )
        assert reached == expected, "reachability differs from independent BFS"
        view, render = measured(
            lambda: svg(graph_data(store, focus="NODE-00000000", limit=100))
        )
        (root / f"graph-{size}.svg").write_text(view)
        affected, invalidation = measured(
            lambda: set(store.invalidate(["NODE-00000000"]))
        )
        assert affected == expected
        assert {x["id"] for x in store.list(state="STALE")} == expected
        assert len(store.list()) == size
        store.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        return {
            "alive_nodes": size,
            "edges": edges,
            "build_seconds": build,
            "reachability_seconds": query,
            "focused_svg_seconds": render,
            "invalidation_seconds": invalidation,
            "affected": len(affected),
            "oracle": "independent BFS agrees exactly",
            "ledger_bytes": (store.root / "ledger.sqlite3").stat().st_size,
        }


def history_case(root, records, alive=1000):
    with Store(root / "history") as store:
        started = time.perf_counter()
        for start in range(0, records, 10000):
            with store.transaction():
                for index in range(start, min(records, start + 10000)):
                    key = f"HISTORY-{index%alive:05d}"
                    store.publish(
                        key,
                        "component",
                        "framework",
                        {"event": index},
                        expected_revision=index // alive,
                    )
            if start % 100000 == 0:
                print(f"history {min(records,start+10000)}/{records}", flush=True)
        build = time.perf_counter() - started
        store.baseline("BASE-HISTORY", "stable synthetic frontier")
        store.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        before = (store.root / "ledger.sqlite3").stat().st_size
        result, compact = measured(store.compact)
        latencies = []
        for rev in [1, max(1, records // alive // 2), records // alive]:
            item, latency = measured(lambda: store.get("HISTORY-00000", rev))
            latencies.append(latency)
            assert item["payload"]["event"] == (rev - 1) * alive
        _, active = measured(
            lambda: graph_data(store, focus="HISTORY-00000", limit=100)
        )
        assert len(store.list()) == alive
        integrity, check = measured(store.check_integrity)
        store.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        logical = (store.root / "ledger.sqlite3").stat().st_size
        packs = sum(p.stat().st_size for p in store.objects.rglob("*") if p.is_file())
        # VACUUM is optional storage reclamation, not required for logical compaction.
        _, vacuum = measured(lambda: store.db.execute("VACUUM"))
        return {
            "historical_and_current_records": records,
            "alive_nodes": alive,
            "build_seconds": build,
            "compaction_seconds": compact,
            "archives": result,
            "history_lookup_max_seconds": max(latencies),
            "active_query_seconds": active,
            "integrity_seconds": check,
            "integrity": integrity,
            "ledger_before_bytes": before,
            "ledger_after_logical_compaction_bytes": logical,
            "ledger_after_vacuum_bytes": (store.root / "ledger.sqlite3").stat().st_size,
            "pack_bytes": packs,
            "vacuum_seconds": vacuum,
        }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--directory", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--sizes", type=int, nargs="+", default=[1000, 10000, 100000])
    p.add_argument("--history", type=int, default=1000000)
    a = p.parse_args()
    a.directory.mkdir(parents=True, exist_ok=True)
    if any(a.directory.iterdir()):
        raise SystemExit("benchmark directory must be empty")
    root = Path(__file__).resolve().parents[1]
    result = {
        "schema_version": 1,
        "kind": "host_performance_measurement_not_release_acceptance",
        "python": sys.version.split()[0],
        "source_files": {
            p.name: bytes_digest(p.read_bytes())
            for p in [
                root / "src/agent_framework/store.py",
                root / "src/agent_framework/graph.py",
                Path(__file__),
            ]
        },
        "graphs": [],
    }
    for size in a.sizes:
        result["graphs"].append(graph_case(a.directory, size))
        write_json(a.output, result, 0o644)
        print(f"graph {size} complete", flush=True)
    result["history"] = history_case(a.directory, a.history)
    result["peak_rss_kib"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    write_json(a.output, result, 0o644)
    print("All graph/history oracles passed.", flush=True)


if __name__ == "__main__":
    main()
