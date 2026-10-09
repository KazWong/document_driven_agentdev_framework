"""The approved registry is the sole source of roles, transitions and gates."""

from __future__ import annotations

from functools import lru_cache
import fnmatch
from pathlib import Path
from typing import Any

from .common import FrameworkError, read_json, safe_relative
from .contracts import validate


@lru_cache(maxsize=1)
def registry() -> dict[str, Any]:
    return read_json(Path(__file__).parent / "data/policy.json")


def transition(state: str, event: str, actor: str) -> str:
    matches = [
        x
        for x in registry()["transitions"]
        if (x["from"], x["event"], x["actor"]) == (state, event, actor)
    ]
    if len(matches) != 1:
        raise FrameworkError(f"illegal lifecycle transition: {state}/{event}/{actor}")
    return matches[0]["to"]


def permissions(
    value: dict[str, Any],
    approved: dict[str, Any] | None = None,
    *,
    automatic: bool = True,
) -> None:
    validate("Permissions", value)
    if automatic and any(
        value[k] for k in ("physical_hardware", "physical_motion", "device_write")
    ):
        raise FrameworkError(
            "physical actions require the separate human hardware procedure"
        )
    # v2.1's backend deliberately has no privileged/credential/destructive port.
    if value["host_privilege"] or value["external_destructive_write"]:
        raise FrameworkError(
            "requested permission is not supported by this backend contract"
        )
    if approved is not None:
        validate("Permissions", approved)
        for key, val in value.items():
            if isinstance(val, bool) and val and not approved[key]:
                raise FrameworkError("permission exceeds approved package: " + key)
        if value["network"] != "none" and approved["network"] != value["network"]:
            raise FrameworkError("network access has not been approved")
        if value["host_filesystem"] != "none" and approved["host_filesystem"] == "none":
            raise FrameworkError("read-only inputs have not been approved")
        if not set(value["credentials"]) <= set(approved["credentials"]):
            raise FrameworkError("credential access has not been approved")


def risk_floor(value: dict[str, Any], consequences: list[str]) -> str:
    validate("Permissions", value)
    levels = {
        "nonfunctional": 0,
        "ordinary_software": 1,
        "concurrency": 2,
        "safety_critical": 2,
        "consequential_external": 2,
        "physical_deployment": 3,
    }
    if not consequences or not set(consequences) <= levels.keys():
        raise FrameworkError("explicit known operation consequences are required")
    floor = max(levels[x] for x in consequences)
    if value["host_privilege"] or value["external_destructive_write"]:
        floor = max(floor, 2)
    if any(value[k] for k in ("physical_hardware", "physical_motion", "device_write")):
        floor = 3
    return "R" + str(floor)


def approval_count(risk: str) -> int:
    try:
        return registry()["risk_policy"]["merge_or_release_approvals"][risk]
    except KeyError as exc:
        raise FrameworkError("unknown risk class") from exc


def needs_safety(risk: str) -> bool:
    return risk in registry()["risk_policy"]["safety_review"]


def in_scope(path: str, scope: dict[str, list[str]]) -> bool:
    path = safe_relative(path)
    # These are controller metadata, never agent-managed production files.
    if path == ".git" or path.startswith(
        (
            ".git/",
            ".agent/runtime/",
            ".agent/knowledge/",
            ".agent/work-items/",
            ".agent-context/",
        )
    ):
        return False
    return any(fnmatch.fnmatchcase(path, p) for p in scope["include"]) and not any(
        fnmatch.fnmatchcase(path, p) for p in scope["exclude"]
    )


def role(name: str) -> dict[str, Any]:
    if name not in registry()["roles"]:
        raise FrameworkError("unknown or removed role: " + name)
    return registry()["roles"][name]
