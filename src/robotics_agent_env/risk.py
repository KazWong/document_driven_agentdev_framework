from __future__ import annotations

from typing import TYPE_CHECKING

from .constants import RISK_POLICY, TRANSIENT_STATES
from .manifest import validate_manifest_data
from .util import AgentEnvError, dump_yaml, safe_actor, sha256_file, utc_now

if TYPE_CHECKING:
    from .workitem import WorkItem


RISK_ORDER = {risk: index for index, risk in enumerate(("R0", "R1", "R2", "R3"))}
PUBLISHED_OR_LATER_STATES = {
    "PR_OPEN", "PR_READY", "CI_VERIFIED", "MERGE_APPROVED", "PROMOTED", "CLOSED",
}


def default_risk_for_kind(kind: str) -> str:
    """Return the framework default risk when the operator did not choose one."""
    normalized = str(kind).strip().lower()
    return "R2" if normalized in {"ros2", "mixed"} else "R1"


def reclassify_work_item(
    item: "WorkItem", target_risk: str, *, actor: str | None = None, note: str = ""
) -> tuple[str, str]:
    """Escalate a work item's risk class and force a fresh planning gate.

    Reclassification is intentionally one-way. Existing documents, role runs,
    plans, candidate commits, and evidence remain historical records, while all
    current plan/candidate/CI/publication bindings are invalidated.
    """
    target = str(target_risk).strip().upper()
    if target not in RISK_POLICY:
        raise AgentEnvError(f"risk class must be one of {', '.join(RISK_POLICY)}")

    status = item.status
    current = str(status.get("risk_class") or item.manifest.get("risk_class", "")).upper()
    if current not in RISK_ORDER:
        raise AgentEnvError(f"current work-item risk class is invalid: {current!r}")
    if RISK_ORDER[target] <= RISK_ORDER[current]:
        raise AgentEnvError(
            f"risk reclassification must escalate the work item; current={current}, requested={target}"
        )
    state = str(status.get("state"))
    if state in TRANSIENT_STATES:
        raise AgentEnvError(f"cannot reclassify while work item is in transient state {state}")
    pull_request = status.get("pull_request")
    if state in PUBLISHED_OR_LATER_STATES or (
        isinstance(pull_request, dict) and pull_request.get("url")
    ):
        raise AgentEnvError(
            "cannot reclassify after remote PR publication; close/reconcile the remote review first"
        )

    identity = safe_actor(actor)
    changed_at = utc_now()
    manifest = dict(item.manifest)
    manifest["risk_class"] = target
    normalized = validate_manifest_data(manifest)

    # Validate the stricter policy before mutating either the manifest or status.
    dump_yaml(item.manifest_path, normalized)
    new_manifest_sha = sha256_file(item.manifest_path)

    gates = set((item.status.get("gate_epochs") or {}).keys()) & {"plan", "merge", "hardware"}
    if gates:
        item.invalidate_gates(gates, event="risk_reclassification_invalidated_gates")

    status = item.status
    history = list(status.get("risk_history") or [])
    history.append({
        "from": current,
        "to": target,
        "actor": identity,
        "note": note,
        "timestamp": changed_at,
    })
    item.update_status(
        {
            "risk_class": target,
            "manifest_sha256": new_manifest_sha,
            "current_plan": None,
            "implementation": None,
            "pull_request": None,
            "ci": None,
            "promotion": None,
            "last_error": None,
            "risk_history": history,
        },
        event="risk_reclassification_state_invalidated",
    )
    item._append_trace(
        "risk_reclassification_applied",
        state,
        "INTAKE" if state != "INTAKE" else "INTAKE",
        {"from": current, "to": target, "note": note},
        actor=identity,
    )
    if state != "INTAKE":
        item.transition(
            state,
            "INTAKE",
            event="risk_reclassification_requires_replan",
            metadata={"from_risk": current, "to_risk": target},
        )
    item.refresh_evidence_index()
    return current, target
