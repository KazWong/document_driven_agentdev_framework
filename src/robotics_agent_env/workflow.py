from __future__ import annotations

from typing import Any

from .codex_runner import dispatch_role
from .util import AgentEnvError
from .verification import run_integration_verification, run_local_verification
from .workitem import WorkItem

STOP_STATES = {"PLANNED", "PR_READY", "CI_VERIFIED", "MERGE_APPROVED", "PROMOTED", "CLOSED", "DIAGNOSED", "BLOCKED"}


def result_passed(result: dict[str, Any], *, allow_not_applicable: bool = False) -> bool:
    decisions = {"pass"}
    if allow_not_applicable:
        decisions.add("not_applicable")
    return (
        result.get("status") == "completed"
        and result.get("decision") in decisions
        and not result.get("scope_change", False)
    )


def run_next(item: WorkItem) -> str:
    state = item.status["state"]
    if state == "INTAKE":
        item.transition("INTAKE", "PLANNING", event="planning_started")
        result = dispatch_role(item, "planner")
        if result_passed(result) and result.get("deliverable_markdown", "").strip():
            item.transition("PLANNING", "PLANNED", event="planning_completed")
        else:
            item.transition("PLANNING", "BLOCKED", event="planning_failed", error=result.get("summary"))
        return item.status["state"]

    if state == "PLAN_APPROVED":
        if item.manifest["isolation"]["strategy"] == "worktree" and not item.status.get("worktree"):
            item.create_worktree()
        item.ensure_implementation_isolation()
        item.transition("PLAN_APPROVED", "IMPLEMENTING", event="implementation_started")
        result = dispatch_role(item, "coder")
        violations = item.scope_violations()
        if violations:
            item.write_artifact("scope-violations.md", "# Scope violations\n\n" + "\n".join(f"- `{path}`" for path in violations))
        if result_passed(result) and not violations:
            item.transition("IMPLEMENTING", "IMPLEMENTED", event="implementation_completed")
        else:
            item.transition("IMPLEMENTING", "DIAGNOSING", event="implementation_failed", error=result.get("summary") or "scope violation")
        return item.status["state"]

    if state == "IMPLEMENTED":
        item.transition("IMPLEMENTED", "LOCAL_VERIFYING", event="local_verification_started")
        summary = run_local_verification(item)
        result = dispatch_role(item, "tester", context={"deterministic_local_verification": summary})
        if summary["passed"] and result_passed(result, allow_not_applicable=summary["not_applicable"]):
            item.transition("LOCAL_VERIFYING", "LOCALLY_VERIFIED", event="local_verification_completed")
        else:
            item.transition("LOCAL_VERIFYING", "DIAGNOSING", event="local_verification_failed", error=result.get("summary"))
        return item.status["state"]

    if state == "LOCALLY_VERIFIED":
        item.transition("LOCALLY_VERIFIED", "ENV_VERIFYING", event="environment_verification_started")
        summary = run_integration_verification(item)
        result = dispatch_role(item, "integration_tester", context={"deterministic_integration_verification": summary})
        if summary["passed"] and result_passed(result, allow_not_applicable=summary["not_applicable"]):
            item.transition("ENV_VERIFYING", "ENV_VERIFIED", event="environment_verification_completed")
        else:
            item.transition("ENV_VERIFYING", "DIAGNOSING", event="environment_verification_failed", error=result.get("summary"))
        return item.status["state"]

    if state == "ENV_VERIFIED":
        item.transition("ENV_VERIFIED", "REVIEWING", event="review_started")
        if item.policy["safety_review"]:
            safety = dispatch_role(item, "safety_reviewer")
            if not result_passed(safety):
                item.transition("REVIEWING", "DIAGNOSING", event="safety_review_failed", error=safety.get("summary"))
                return item.status["state"]
        review = dispatch_role(item, "reviewer")
        if result_passed(review):
            item.transition("REVIEWING", "REVIEWED", event="review_completed")
        else:
            item.transition("REVIEWING", "DIAGNOSING", event="review_failed", error=review.get("summary"))
        return item.status["state"]

    if state == "REVIEWED":
        item.transition("REVIEWED", "PR_PREPARING", event="pull_request_preparation_started")
        result = dispatch_role(item, "review_requester")
        if result_passed(result):
            item.transition("PR_PREPARING", "PR_READY", event="pull_request_preparation_completed")
        else:
            item.transition("PR_PREPARING", "BLOCKED", event="pull_request_preparation_failed", error=result.get("summary"))
        return item.status["state"]

    if state == "DIAGNOSING":
        result = dispatch_role(item, "debugger")
        if result.get("status") == "completed":
            item.transition("DIAGNOSING", "DIAGNOSED", event="diagnosis_completed")
        else:
            item.transition("DIAGNOSING", "BLOCKED", event="diagnosis_failed", error=result.get("summary"))
        return item.status["state"]

    raise AgentEnvError(f"no automatic action is defined for state {state}")


def run_until_gate(item: WorkItem, *, one_step: bool = False) -> str:
    first = True
    while first or item.status["state"] not in STOP_STATES:
        first = False
        run_next(item)
        if one_step:
            break
    return item.status["state"]


def resolve_diagnosis(item: WorkItem, route: str) -> str:
    if item.status["state"] != "DIAGNOSED":
        raise AgentEnvError("diagnosis can be resolved only from DIAGNOSED")
    routes = {
        "implementation": "PLAN_APPROVED",
        "plan": "INTAKE",
        "local-test": "IMPLEMENTED",
        "environment": "LOCALLY_VERIFIED",
        "blocked": "BLOCKED",
    }
    try:
        target = routes[route]
    except KeyError as exc:
        raise AgentEnvError(f"route must be one of {', '.join(routes)}") from exc
    if route == "plan":
        item.invalidate_gates(
            {"plan", "pr", "merge", "hardware"},
            event="diagnosis_invalidated_all_gates",
        )
    elif route != "blocked":
        item.invalidate_gates(
            {"pr", "merge", "hardware"},
            event="diagnosis_invalidated_downstream_gates",
        )
    item.transition("DIAGNOSED", target, event="diagnosis_routed", metadata={"route": route})
    return target
