#!/usr/bin/env python3
"""Host conformance checks. Passing these checks never grants release approval."""
import argparse
import ast
import json
from pathlib import Path
import subprocess
import sys
import tomllib

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from jsonschema import Draft202012Validator
import yaml
from agent_framework.common import FrameworkError, bytes_digest, read_json
from agent_framework.contracts import validate_blueprint, validate_plan
from generate_projection import outputs


def require(condition, message):
    if not condition:
        raise FrameworkError(message)


def check(root: Path, *, git_tree=False, benchmark=None):
    checks = []
    project = tomllib.loads((root / "pyproject.toml").read_text())
    require(
        project["project"]["version"]
        == (root / "VERSION").read_text().strip()
        == "2.1.0",
        "version mismatch",
    )
    for path, expected in outputs(root).items():
        require(
            path.is_file() and path.read_text() == expected,
            "projection drift: " + str(path),
        )
    schema = read_json(root / "src/agent_framework/data/contracts.schema.json")
    Draft202012Validator.check_schema(schema)
    checks.append("versions, schema and generated projections")

    design = root / ".agent/design"
    bp = read_json(design / "blueprint.json")
    validate_blueprint(bp)
    require(
        {r["id"] for r in bp["requirements"]}
        == {f"REQ-FW-{i:03d}" for i in range(1, 23)},
        "missing framework requirement",
    )
    require(
        {r["id"] for r in bp["verification_obligations"]}
        == {f"VER-FW-{i:03d}" for i in range(1, 23)},
        "missing verification obligation",
    )
    mappings = read_json(design / "implementation-map.json")["requirements"]
    require(
        len(mappings) == 22
        and {r["requirement"] for r in mappings}
        == {r["id"] for r in bp["requirements"]},
        "incomplete implementation mapping",
    )
    for row in mappings:
        require(
            row["modules"] and row["host_test_files"] and row["tasks"],
            "empty requirement mapping",
        )
        for path in row["modules"] + row["host_test_files"]:
            require(
                (root / path).is_file(),
                "mapped implementation/test file missing: " + path,
            )
    decisions = read_json(design / "decision-coverage.json")["decisions"]
    require(
        len(decisions) == 43
        and {d["decision"] for d in decisions} == {f"D-{i:03d}" for i in range(1, 44)},
        "decision coverage mismatch",
    )
    cases = read_json(design / "acceptance-cases.json")["cases"]
    require(
        len(cases) == 31
        and {c["id"] for c in cases} == {f"T-{i:03d}" for i in range(1, 32)},
        "acceptance scenario mismatch",
    )
    example = read_json(root / "examples/blueprint.json")
    validate_blueprint(example)
    validate_plan(read_json(root / "examples/plan.json"), example)
    checks.append(
        "22 requirements, 22 VER obligations, 43 decisions, 31 scenarios and draft examples"
    )
    trace = read_json(design / "candidate-trace.json")
    requirement_ids = {r["id"] for r in bp["requirements"]}
    design_ids = {r["id"] for r in bp["components"] + bp["interfaces"]}
    task_ids = {
        r["id"] for r in read_json(design / "implementation-plan.json")["tasks"]
    }
    paths = [row["path"] for row in trace["changes"]]
    require(len(paths) == len(set(paths)), "duplicate candidate trace path")
    for row in trace["changes"]:
        require(
            bool(row["requirement_ids"])
            and set(row["requirement_ids"]) <= requirement_ids
            and bool(row["design_ids"])
            and set(row["design_ids"]) <= design_ids
            and bool(row["task_ids"])
            and set(row["task_ids"]) <= task_ids,
            "invalid candidate trace IDs",
        )
    if git_tree:
        changed = subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "diff",
                "--no-renames",
                "--name-only",
                trace["baseline_sha"],
                "HEAD",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        require(
            set(changed.stdout.splitlines()) == set(paths),
            "candidate diff and trace paths disagree",
        )
    checks.append("complete candidate path-to-requirement/design/task trace")

    policy = read_json(root / "src/agent_framework/data/policy.json")
    require(
        set(policy["roles"])
        == {"planner", "coder", "tester", "reviewer", "safety_reviewer", "debugger"},
        "role registry drift",
    )
    compose = yaml.safe_load((root / "compose.yaml").read_text())
    require(
        set(compose["services"]) == {"main-development", "generic-test"},
        "permanent environment set changed",
    )
    entrypoints = sorted(
        [p for p in (root / "bin").iterdir() if p.is_file()]
        + list((root / "scripts").glob("*.py"))
    )
    for path in entrypoints:
        require(
            path.stat().st_mode & 0o111,
            "required executable mode missing: " + str(path.relative_to(root)),
        )
    if git_tree:
        result = subprocess.run(
            ["git", "-C", str(root), "ls-tree", "-r", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        modes = {
            line.split("\t", 1)[1]: line.split()[0]
            for line in result.stdout.splitlines()
        }
        for path in entrypoints:
            require(
                modes.get(path.relative_to(root).as_posix()) == "100755",
                "committed executable mode missing: " + str(path),
            )
    checks.append("role registry, two environment definitions and executable modes")

    # A targeted guard against reintroducing the old domain/language dispatcher.
    # This complements the unknown-provider behavioral test; it is not a proof
    # that every possible future implementation is technology neutral.
    forbidden = {"ros2", "firmware", "mixed", "cpp", "cxx", "python", "shell"}
    for path in (root / "src/agent_framework").glob("*.py"):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, (ast.Compare, ast.Match)):
                values = {
                    x.value
                    for x in ast.walk(node)
                    if isinstance(x, ast.Constant) and isinstance(x.value, str)
                }
                require(
                    not values & forbidden,
                    "domain/language branch in core: " + str(path),
                )
    checks.append("core syntax and obsolete domain-dispatch guard")

    if benchmark:
        data = read_json(benchmark)
        budgets = read_json(root / "config/performance-budgets.json")
        for name, recorded in data["source_files"].items():
            path = (
                root
                / ("scripts" if name == "benchmark_graph.py" else "src/agent_framework")
                / name
            )
            require(
                bytes_digest(path.read_bytes()) == recorded,
                "benchmark is for different source: " + name,
            )
        require(
            sorted(g["alive_nodes"] for g in data["graphs"])
            == budgets["required_graph_sizes"],
            "incomplete graph benchmark",
        )
        for graph in data["graphs"]:
            for metric, maximum in budgets["graph_max_seconds"].items():
                require(
                    graph[metric] <= maximum,
                    "graph performance budget exceeded: " + metric,
                )
        require(
            data["history"]["historical_and_current_records"]
            == budgets["required_history_records"],
            "incomplete archived-history benchmark",
        )
        for metric, maximum in budgets["history_max_seconds"].items():
            require(
                data["history"][metric] <= maximum,
                "history performance budget exceeded: " + metric,
            )
        require(
            data["peak_rss_kib"] <= budgets["max_peak_rss_kib"],
            "memory budget exceeded",
        )
        checks.append("source-bound measured graph/history regression budgets")
    return {"status": "passed", "authority": "host_conformance_only", "checks": checks}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--git-tree", action="store_true")
    p.add_argument("--benchmark", type=Path)
    args = p.parse_args()
    try:
        print(
            json.dumps(
                check(
                    Path(__file__).resolve().parents[1],
                    git_tree=args.git_tree,
                    benchmark=args.benchmark,
                ),
                indent=2,
            )
        )
    except (FrameworkError, OSError, ValueError) as exc:
        raise SystemExit("Blocked: " + str(exc))


if __name__ == "__main__":
    main()
