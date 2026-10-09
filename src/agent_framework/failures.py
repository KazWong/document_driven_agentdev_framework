"""One-shot owner routing. No hidden retry loops or silent policy relaxation."""

from __future__ import annotations

from typing import Any

from .common import FrameworkError, digest

OWNERS = {
    "candidate_failed": "coder",
    "test_failure": "tester",
    "environment_failure": "environment_project",
    "provider_failure": "provider_project",
    "bootstrap_failure": "bootstrap",
    "unsupported_requirement": "planner",
    "transient_failure": "human",
    "unknown_failure": "debugger",
}


def classify(
    status: str,
    affected: list[str],
    material: dict[str, Any],
    previous: list[dict[str, Any]],
) -> dict[str, Any]:
    if status not in OWNERS:
        raise FrameworkError("unknown failure class")
    owner = OWNERS[status]
    identity = digest(
        {
            "owner": owner,
            "affected": sorted(set(affected)),
            "class": status,
            "material": material,
        }
    )
    repeated = any(x["identity"] == identity for x in previous)
    return {
        "class": status,
        "owner": "debugger" if repeated else owner,
        "original_owner": owner,
        "affected": sorted(set(affected)),
        "material": material,
        "identity": identity,
        "repeated": repeated,
        "automatic_retry_budget": 0,
    }
