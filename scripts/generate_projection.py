#!/usr/bin/env python3
"""Regenerate public schema, policy and role-document projections from runtime data."""
import argparse
from pathlib import Path
import json
import sys


def outputs(root):
    data = root / "src/agent_framework/data"
    policy = json.loads((data / "policy.json").read_text())
    result = {
        root / "config/policy.json": (data / "policy.json").read_text(),
        root
        / "schemas/contracts.schema.json": (data / "contracts.schema.json").read_text(),
    }
    for role, value in policy["roles"].items():
        result[root / "docs/roles" / f"{role}.md"] = (
            "# "
            + role.replace("_", " ").title()
            + " policy\n\nGenerated from `src/agent_framework/data/policy.json`.\n\nProduct access: "
            + value["product"]
            + ".\n\nAllowed outputs: "
            + ", ".join(value["role_outputs"])
            + ".\n\nIndependent test access: "
            + value["independent_tests"]
            + ".\n\nForbidden operations: "
            + ", ".join(value["forbidden"])
            + ".\n\nThe controller validates role, stage, input digest and exact candidate. Missing isolation blocks execution. This role grants no human approval and cannot mutate Git or controller state.\n"
        )
    return result


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--check", action="store_true")
    a = p.parse_args()
    root = Path(__file__).resolve().parents[1]
    drift = []
    for path, text in outputs(root).items():
        if a.check:
            if not path.exists() or path.read_text() != text:
                drift.append(str(path.relative_to(root)))
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
    if drift:
        raise SystemExit("Projection drift: " + ", ".join(drift))
    print(
        "Policy, schema and role projections agree."
        if a.check
        else "Projections regenerated."
    )


if __name__ == "__main__":
    main()
