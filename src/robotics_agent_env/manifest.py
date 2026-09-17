from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .constants import RISK_POLICY
from .util import AgentEnvError, load_yaml, resolve_workspace_path

ID_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{1,63}")
VALID_PROJECT_KINDS = {"generic", "ros2", "firmware", "mixed"}
VALID_INTEGRATION_ACTIONS = {"doctor", "sim", "smoke", "test"}
PROHIBITED_AUTOMATIC_LANES = {"physical-hardware", "hil", "hardware", "robot"}


def _string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AgentEnvError(f"manifest field '{field}' must be a non-empty string")
    return value.strip()


def _string_list(value: Any, field: str, *, allow_empty: bool = True) -> list[str]:
    if value is None and allow_empty:
        return []
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise AgentEnvError(f"manifest field '{field}' must be a list of non-empty strings")
    result = [item.strip() for item in value]
    if not allow_empty and not result:
        raise AgentEnvError(f"manifest field '{field}' must not be empty")
    return result


def validate_manifest_data(raw: dict[str, Any]) -> dict[str, Any]:
    if raw.get("schema_version", 1) != 1:
        raise AgentEnvError(f"unsupported manifest schema_version: {raw.get('schema_version')!r}")
    work_id = _string(raw.get("id"), "id")
    if not ID_PATTERN.fullmatch(work_id):
        raise AgentEnvError("manifest id must start with a letter and use only letters, digits, '.', '_', or '-'")
    title = _string(raw.get("title"), "title")
    repository = resolve_workspace_path(_string(raw.get("repository"), "repository"))
    if not repository.exists():
        raise AgentEnvError(f"manifest repository does not exist: {repository}")
    risk_class = _string(raw.get("risk_class"), "risk_class").upper()
    if risk_class not in RISK_POLICY:
        raise AgentEnvError(f"risk_class must be one of {', '.join(RISK_POLICY)}")
    project_kind = str(raw.get("project_kind", "generic")).strip().lower()
    if project_kind not in VALID_PROJECT_KINDS:
        raise AgentEnvError(f"project_kind must be one of {', '.join(sorted(VALID_PROJECT_KINDS))}")
    goal = _string(raw.get("goal"), "goal")
    acceptance = _string_list(raw.get("acceptance_criteria"), "acceptance_criteria", allow_empty=False)

    scope_raw = raw.get("scope")
    if not isinstance(scope_raw, dict):
        raise AgentEnvError("manifest field 'scope' must be a mapping")
    include = _string_list(scope_raw.get("include"), "scope.include", allow_empty=False)
    exclude = _string_list(scope_raw.get("exclude", []), "scope.exclude")

    verification_raw = raw.get("verification", {})
    if not isinstance(verification_raw, dict):
        raise AgentEnvError("manifest field 'verification' must be a mapping")

    local_raw = verification_raw.get("local", [])
    if not isinstance(local_raw, list):
        raise AgentEnvError("verification.local must be a list")
    local: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(local_raw):
        if not isinstance(item, dict):
            raise AgentEnvError(f"verification.local[{index}] must be a mapping")
        item_id = _string(item.get("id", f"local-{index + 1}"), f"verification.local[{index}].id")
        if item_id in seen_ids:
            raise AgentEnvError(f"duplicate local verification id: {item_id}")
        seen_ids.add(item_id)
        command = item.get("command")
        if not isinstance(command, list) or not command or any(not isinstance(arg, str) or not arg for arg in command):
            raise AgentEnvError(f"verification.local[{index}].command must be a non-empty argv list")
        timeout = item.get("timeout_seconds", 900)
        if not isinstance(timeout, (int, float)) or not 1 <= float(timeout) <= 7200:
            raise AgentEnvError(f"verification.local[{index}].timeout_seconds must be 1..7200")
        local.append({"id": item_id, "command": list(command), "timeout_seconds": float(timeout)})

    integration_raw = verification_raw.get("integration", [])
    if not isinstance(integration_raw, list):
        raise AgentEnvError("verification.integration must be a list")
    integration: list[dict[str, Any]] = []
    for index, item in enumerate(integration_raw):
        if not isinstance(item, dict):
            raise AgentEnvError(f"verification.integration[{index}] must be a mapping")
        lane = _string(item.get("lane"), f"verification.integration[{index}].lane").lower()
        if lane == "ros2-gazebo":
            lane = "ros2-humble"
        if lane == "ros2-jazzy":
            raise AgentEnvError("ros2-jazzy was retired; use the external ros2-humble lane")
        if lane in PROHIBITED_AUTOMATIC_LANES:
            raise AgentEnvError(f"automatic verification cannot use physical lane '{lane}'")
        action = str(item.get("action", "test")).strip().lower()
        if action not in VALID_INTEGRATION_ACTIONS:
            raise AgentEnvError(f"integration action must be one of {', '.join(sorted(VALID_INTEGRATION_ACTIONS))}")
        args = _string_list(item.get("args", []), f"verification.integration[{index}].args")
        integration.append({"lane": lane, "action": action, "args": args})

    policy = RISK_POLICY[risk_class]
    if policy["requires_local"] and not local:
        raise AgentEnvError(f"{risk_class} work requires local verification")
    if policy["requires_integration"] and not integration:
        raise AgentEnvError(f"{risk_class} work requires an integration lane")
    if project_kind in {"ros2", "mixed"} and not any(entry["lane"] == "ros2-humble" for entry in integration):
        raise AgentEnvError("ROS 2 work must include the required 'ros2-humble' lane")

    isolation_raw = raw.get("isolation", {})
    if not isinstance(isolation_raw, dict):
        raise AgentEnvError("manifest field 'isolation' must be a mapping")
    strategy = str(isolation_raw.get("strategy", "worktree")).strip().lower()
    if strategy not in {"worktree", "in-place"}:
        raise AgentEnvError("isolation.strategy must be 'worktree' or 'in-place'")
    if strategy == "in-place" and risk_class in {"R2", "R3"}:
        raise AgentEnvError("R2/R3 work must use a Git worktree")

    promotion_raw = raw.get("promotion", {})
    if not isinstance(promotion_raw, dict):
        raise AgentEnvError("manifest field 'promotion' must be a mapping")
    physical = str(promotion_raw.get("physical_hardware", "prohibited")).strip().lower()
    if physical not in {"prohibited", "human-approved"}:
        raise AgentEnvError("promotion.physical_hardware must be prohibited or human-approved")
    if risk_class == "R3" and physical != "human-approved":
        raise AgentEnvError("R3 work must explicitly set physical_hardware: human-approved")

    rollback_raw = raw.get("rollback", {})
    if not isinstance(rollback_raw, dict):
        raise AgentEnvError("manifest field 'rollback' must be a mapping")
    human_gates_raw = raw.get("human_gates", {})
    if not isinstance(human_gates_raw, dict):
        raise AgentEnvError("manifest field 'human_gates' must be a mapping")

    normalized = dict(raw)
    normalized.update({
        "schema_version": 1,
        "id": work_id,
        "title": title,
        "repository": str(repository),
        "base_branch": str(raw.get("base_branch", "main")).strip() or "main",
        "risk_class": risk_class,
        "project_kind": project_kind,
        "goal": goal,
        "scope": {"include": include, "exclude": exclude},
        "acceptance_criteria": acceptance,
        "verification": {"local": local, "integration": integration},
        "isolation": {"strategy": strategy},
        "rollback": {"method": str(rollback_raw.get("method", "revert_commit"))},
        "human_gates": human_gates_raw,
        "promotion": {**promotion_raw, "physical_hardware": physical},
    })
    return normalized


def load_and_validate_manifest(path: Path) -> dict[str, Any]:
    return validate_manifest_data(load_yaml(path))
