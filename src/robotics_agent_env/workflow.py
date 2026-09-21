from __future__ import annotations

from typing import Any

from .codex_runner import dispatch_role
from .scm import publish_pull_request
from .util import AgentEnvError, git_sha
from .verification import run_integration_verification, run_local_verification
from .workitem import WorkItem

STOP_STATES = {
    "PLANNED", "PR_OPEN", "PR_READY", "CI_VERIFIED", "MERGE_APPROVED",
    "PROMOTED", "CLOSED", "DIAGNOSED", "BLOCKED",
}


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
        if not item.active_documents():
            message = (
                f"{item.work_id} has no active project documents; import at least one with "
                f"'agentctl update {item.work_id} --document <path>'"
            )
            item.transition("INTAKE", "BLOCKED", event="planning_blocked_missing_documents", error=message)
            return item.status["state"]
        if item.manifest["isolation"]["strategy"] == "worktree" and not item.status.get("worktree"):
            item.create_worktree()
        item.prepare_agent_context()
        item.transition("INTAKE", "PLANNING", event="planning_started")
        try:
            result = dispatch_role(item, "planner")
        except AgentEnvError as exc:
            item.transition("PLANNING", "BLOCKED", event="planning_failed", error=str(exc))
            return item.status["state"]
        if result_passed(result) and result.get("deliverable_markdown", "").strip() and item.status.get("current_plan"):
            item.transition("PLANNING", "PLANNED", event="planning_completed")
        else:
            item.transition("PLANNING", "BLOCKED", event="planning_failed", error=result.get("summary") or "planner did not produce an approved plan artifact")
        return item.status["state"]

    if state == "PLAN_APPROVED":
        if item.manifest["isolation"]["strategy"] == "worktree" and not item.status.get("worktree"):
            item.create_worktree()
        item.ensure_implementation_isolation()
        item.prepare_agent_context()
        expected_head = git_sha(item.repo)
        item.transition("PLAN_APPROVED", "IMPLEMENTING", event="implementation_started", metadata={"starting_sha": expected_head})
        result = dispatch_role(item, "coder")
        if not result_passed(result):
            item.transition("IMPLEMENTING", "DIAGNOSING", event="implementation_failed", error=result.get("summary"))
            return item.status["state"]
        try:
            candidate = item.create_candidate_commit(expected_head=expected_head)
            item.transition("IMPLEMENTING", "IMPLEMENTED", event="implementation_completed", metadata={"candidate_sha": candidate})
        except AgentEnvError as exc:
            item.write_artifact("candidate-failure.md", f"# Candidate commit failure\n\n{exc}")
            item.transition("IMPLEMENTING", "DIAGNOSING", event="candidate_commit_failed", error=str(exc))
        return item.status["state"]

    if state == "IMPLEMENTED":
        item.prepare_agent_context()
        item.transition("IMPLEMENTED", "LOCAL_VERIFYING", event="local_verification_started")
        summary = run_local_verification(item)
        result = dispatch_role(item, "tester", context={"deterministic_local_verification": summary})
        if summary["passed"] and result_passed(result, allow_not_applicable=summary["not_applicable"]):
            try:
                candidate = item.record_candidate_stage("local", summary.get("candidate_sha"))
                item.transition("LOCAL_VERIFYING", "LOCALLY_VERIFIED", event="local_verification_completed", metadata={"candidate_sha": candidate})
            except AgentEnvError as exc:
                item.transition("LOCAL_VERIFYING", "DIAGNOSING", event="candidate_changed_during_local_verification", error=str(exc))
        else:
            item.transition("LOCAL_VERIFYING", "DIAGNOSING", event="local_verification_failed", error=result.get("summary") or "deterministic local verification failed")
        return item.status["state"]

    if state == "LOCALLY_VERIFIED":
        item.prepare_agent_context()
        item.transition("LOCALLY_VERIFIED", "ENV_VERIFYING", event="environment_verification_started")
        summary = run_integration_verification(item)
        result = dispatch_role(item, "integration_tester", context={"deterministic_integration_verification": summary})
        if summary["passed"] and result_passed(result, allow_not_applicable=summary["not_applicable"]):
            try:
                candidate = item.record_candidate_stage("integration", summary.get("candidate_sha"))
                item.transition("ENV_VERIFYING", "ENV_VERIFIED", event="environment_verification_completed", metadata={"candidate_sha": candidate})
            except AgentEnvError as exc:
                item.transition("ENV_VERIFYING", "DIAGNOSING", event="candidate_changed_during_environment_verification", error=str(exc))
        else:
            item.transition("ENV_VERIFYING", "DIAGNOSING", event="environment_verification_failed", error=result.get("summary") or "deterministic integration verification failed")
        return item.status["state"]

    if state == "ENV_VERIFIED":
        item.prepare_agent_context()
        item.transition("ENV_VERIFIED", "REVIEWING", event="review_started")
        if item.policy["safety_review"]:
            safety = dispatch_role(item, "safety_reviewer")
            if not result_passed(safety):
                item.transition("REVIEWING", "DIAGNOSING", event="safety_review_failed", error=safety.get("summary"))
                return item.status["state"]
        review = dispatch_role(item, "reviewer")
        if result_passed(review):
            try:
                candidate = item.record_candidate_stage("review")
                item.transition("REVIEWING", "REVIEWED", event="review_completed", metadata={"candidate_sha": candidate})
            except AgentEnvError as exc:
                item.transition("REVIEWING", "DIAGNOSING", event="candidate_changed_during_review", error=str(exc))
        else:
            item.transition("REVIEWING", "DIAGNOSING", event="review_failed", error=review.get("summary"))
        return item.status["state"]

    if state == "REVIEWED":
        item.prepare_agent_context()
        item.transition("REVIEWED", "PR_CREATING", event="pull_request_creation_started")
        result = dispatch_role(item, "review_requester")
        if not result_passed(result):
            item.transition("PR_CREATING", "BLOCKED", event="pull_request_preparation_failed", error=result.get("summary"))
            return item.status["state"]
        try:
            pull_request = publish_pull_request(item)
            item.transition(
                "PR_CREATING", "PR_OPEN", event="pull_request_creation_completed",
                metadata={"provider": pull_request.get("provider"), "url": pull_request.get("url"), "head_sha": pull_request.get("head_sha")},
            )
        except AgentEnvError as exc:
            item.transition("PR_CREATING", "BLOCKED", event="pull_request_creation_failed", error=str(exc))
        return item.status["state"]

    if state == "DIAGNOSING":
        item.prepare_agent_context()
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
    if route not in {"implementation", "plan", "local-test", "environment", "blocked"}:
        raise AgentEnvError("route must be one of implementation, plan, local-test, environment, blocked")
    return item.invalidate_execution(route)
