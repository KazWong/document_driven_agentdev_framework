from __future__ import annotations

import fnmatch
import os
import re
import shutil
from pathlib import Path
from typing import Any

from .constants import ALL_STATES, PROTECTED_BRANCHES, RISK_POLICY, TRANSIENT_STATES
from .manifest import load_and_validate_manifest
from .util import (
    AgentEnvError, append_jsonl, atomic_write_json, atomic_write_text, dump_yaml,
    file_lock, git, git_branch, git_changed_paths, git_root, git_sha, load_json,
    load_yaml, safe_actor, sha256_file, sha256_json, slugify, state_root, utc_now,
)


class WorkItem:
    def __init__(self, work_id: str, root: Path | None = None) -> None:
        self.state_root = (root or state_root()).resolve()
        self.work_id = work_id
        self.path = self.state_root / "work-items" / work_id
        self.manifest_path = self.path / "request.yaml"
        self.status_path = self.path / "status.json"
        self.trace_path = self.path / "trace.jsonl"
        self.lock_path = self.path / ".lock"
        self.artifacts_path = self.path / "artifacts"
        self.runs_path = self.path / "runs"
        self.approvals_path = self.path / "approvals"
        self.evidence_index_path = self.path / "evidence-index.json"

    @classmethod
    def create(cls, manifest_source: Path, *, root: Path | None = None) -> "WorkItem":
        manifest = load_and_validate_manifest(manifest_source)
        item = cls(manifest["id"], root=root)
        if item.path.exists():
            raise AgentEnvError(f"work item already exists: {item.work_id}")
        item.path.mkdir(parents=True)
        item.artifacts_path.mkdir()
        item.runs_path.mkdir()
        item.approvals_path.mkdir()
        dump_yaml(item.manifest_path, manifest)
        repository = git_root(Path(manifest["repository"]))
        status = {
            "schema_version": 1,
            "id": item.work_id,
            "title": manifest["title"],
            "risk_class": manifest["risk_class"],
            "project_kind": manifest["project_kind"],
            "state": "INTAKE",
            "last_stable_state": "INTAKE",
            "revision": 1,
            "created_at": utc_now(),
            "updated_at": utc_now(),
            "manifest_sha256": sha256_file(item.manifest_path),
            "repository": str(repository),
            "base_branch": manifest["base_branch"],
            "branch": None,
            "worktree": None,
            "baseline_sha": git_sha(repository, manifest["base_branch"]),
            "last_error": None,
            "role_runs": {},
            "ci": None,
            "promotion": None,
            "gate_epochs": {"plan": 0, "pr": 0, "merge": 0, "hardware": 0},
        }
        atomic_write_json(item.status_path, status)
        item._append_trace("work_item_created", None, "INTAKE", {
            "manifest_sha256": status["manifest_sha256"], "repository": str(repository)
        })
        item.refresh_evidence_index()
        return item

    @classmethod
    def open(cls, work_id: str, root: Path | None = None) -> "WorkItem":
        item = cls(work_id, root=root)
        if not item.status_path.is_file():
            raise AgentEnvError(f"unknown work item: {work_id}")
        return item

    @property
    def manifest(self) -> dict[str, Any]:
        return load_yaml(self.manifest_path)

    @property
    def status(self) -> dict[str, Any]:
        status = load_json(self.status_path)
        if status.get("state") not in ALL_STATES:
            raise AgentEnvError(f"invalid workflow state: {status.get('state')!r}")
        return status

    @property
    def repo(self) -> Path:
        status = self.status
        return Path(status.get("worktree") or status["repository"]).resolve()

    @property
    def policy(self) -> dict[str, Any]:
        return RISK_POLICY[self.manifest["risk_class"]]

    def _append_trace(
        self, event: str, from_state: str | None, to_state: str | None,
        metadata: dict[str, Any] | None = None, actor: str | None = None,
    ) -> None:
        append_jsonl(self.trace_path, {
            "timestamp": utc_now(),
            "work_item": self.work_id,
            "event": event,
            "actor": actor or os.environ.get("USER") or "system",
            "from_state": from_state,
            "to_state": to_state,
            "metadata": metadata or {},
        })

    def transition(
        self, expected: str | set[str], target: str, *, event: str,
        metadata: dict[str, Any] | None = None, error: str | None = None,
    ) -> dict[str, Any]:
        expected_states = {expected} if isinstance(expected, str) else set(expected)
        if target not in ALL_STATES:
            raise AgentEnvError(f"invalid target state: {target}")
        with file_lock(self.lock_path):
            status = self.status
            current = status["state"]
            if current not in expected_states:
                raise AgentEnvError(
                    f"cannot transition {self.work_id} from {current} to {target}; expected {', '.join(sorted(expected_states))}"
                )
            status["state"] = target
            status["revision"] = int(status.get("revision", 0)) + 1
            status["updated_at"] = utc_now()
            status["last_error"] = error
            if target not in TRANSIENT_STATES:
                status["last_stable_state"] = target
            atomic_write_json(self.status_path, status)
            self._append_trace(event, current, target, metadata)
        self.refresh_evidence_index()
        return status

    def update_status(self, updates: dict[str, Any], *, event: str) -> dict[str, Any]:
        with file_lock(self.lock_path):
            status = self.status
            state = status["state"]
            status.update(updates)
            status["revision"] = int(status.get("revision", 0)) + 1
            status["updated_at"] = utc_now()
            atomic_write_json(self.status_path, status)
            self._append_trace(event, state, state, updates)
        self.refresh_evidence_index()
        return status

    def create_worktree(self, branch: str | None = None) -> Path:
        manifest = self.manifest
        status = self.status
        if status.get("worktree"):
            return Path(status["worktree"])
        repository = Path(status["repository"])
        strategy = manifest["isolation"]["strategy"]
        if strategy == "in-place":
            current = git_branch(repository)
            if current in PROTECTED_BRANCHES:
                raise AgentEnvError(f"in-place work is forbidden on protected branch '{current}'")
            self.update_status({"branch": current}, event="in_place_isolation_accepted")
            return repository
        branch_name = branch or f"agent/{self.work_id.lower()}-{slugify(manifest['title'])}"
        if not re.fullmatch(r"[A-Za-z0-9._/-]{1,160}", branch_name):
            raise AgentEnvError(f"invalid Git branch name: {branch_name}")
        worktree = (self.state_root / "worktrees" / repository.name / self.work_id).resolve()
        if worktree.exists():
            raise AgentEnvError(f"worktree path already exists: {worktree}")
        worktree.parent.mkdir(parents=True, exist_ok=True)
        completed = git(repository, "worktree", "add", "-b", branch_name, str(worktree), manifest["base_branch"], check=False)
        if completed.returncode != 0:
            raise AgentEnvError(f"failed to create worktree: {(completed.stderr or completed.stdout).strip()}")
        self.update_status({"branch": branch_name, "worktree": str(worktree), "baseline_sha": git_sha(worktree)}, event="worktree_created")
        return worktree

    def ensure_implementation_isolation(self) -> None:
        manifest = self.manifest
        status = self.status
        if manifest["isolation"]["strategy"] == "worktree" and not status.get("worktree"):
            raise AgentEnvError(f"implementation requires a worktree; run 'agentctl worktree create {self.work_id}'")
        branch = git_branch(self.repo)
        if branch in PROTECTED_BRANCHES:
            raise AgentEnvError(f"implementation is forbidden on protected branch '{branch}'")

    def scope_violations(self) -> list[str]:
        scope = self.manifest["scope"]
        violations: list[str] = []
        baseline = self.status.get("baseline_sha")
        for path in git_changed_paths(self.repo, baseline=baseline):
            included = any(_path_matches(path, pattern) for pattern in scope["include"])
            excluded = any(_path_matches(path, pattern) for pattern in scope.get("exclude", []))
            if not included or excluded:
                violations.append(path)
        return violations

    def new_run_dir(self, role: str) -> Path:
        role_root = self.runs_path / role
        role_root.mkdir(parents=True, exist_ok=True)
        numbers = [int(path.name) for path in role_root.iterdir() if path.is_dir() and path.name.isdigit()]
        run_dir = role_root / f"{max(numbers, default=0) + 1:04d}"
        run_dir.mkdir()
        return run_dir

    def record_role_run(self, role: str, run_dir: Path, result: dict[str, Any], returncode: int) -> None:
        with file_lock(self.lock_path):
            status = self.status
            role_runs = dict(status.get("role_runs", {}))
            entries = list(role_runs.get(role, []))
            entries.append({
                "timestamp": utc_now(),
                "run_dir": str(run_dir.relative_to(self.path)),
                "returncode": returncode,
                "status": result.get("status"),
                "decision": result.get("decision"),
                "summary": result.get("summary"),
            })
            role_runs[role] = entries
            status["role_runs"] = role_runs
            status["revision"] = int(status.get("revision", 0)) + 1
            status["updated_at"] = utc_now()
            atomic_write_json(self.status_path, status)
        self._append_trace("role_run_recorded", self.status["state"], self.status["state"], {
            "role": role, "run_dir": str(run_dir.relative_to(self.path)), "returncode": returncode
        })
        self.refresh_evidence_index()

    def write_artifact(self, filename: str, text: str) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", filename):
            raise AgentEnvError(f"invalid artifact filename: {filename}")
        target = self.artifacts_path / filename
        atomic_write_text(target, text.rstrip() + "\n")
        self.refresh_evidence_index()
        return target

    def _approval_context(self, gate: str) -> tuple[str, dict[str, Any]]:
        gate = gate.lower()
        status = self.status
        epochs = status.get("gate_epochs", {})
        context: dict[str, Any] = {
            "work_item": self.work_id,
            "gate": gate,
            "epoch": int(epochs.get(gate, 0)),
            "manifest_sha256": sha256_file(self.manifest_path),
        }
        if gate == "plan":
            plan = self.artifacts_path / "plan.md"
            if not plan.is_file():
                raise AgentEnvError("plan approval requires artifacts/plan.md")
            context["plan_sha256"] = sha256_file(plan)
        elif gate == "pr":
            body = self.artifacts_path / "pull-request.md"
            if not body.is_file():
                raise AgentEnvError("PR approval requires artifacts/pull-request.md")
            context.update({
                "pull_request_sha256": sha256_file(body),
                "git_sha": git_sha(self.repo),
            })
        elif gate in {"merge", "hardware"}:
            ci = status.get("ci")
            current_sha = git_sha(self.repo)
            if not isinstance(ci, dict) or ci.get("status") != "passed":
                raise AgentEnvError(f"{gate} approval requires a passing recorded CI result")
            if ci.get("commit") != current_sha:
                raise AgentEnvError(
                    f"recorded CI commit {ci.get('commit')} does not match current HEAD {current_sha}"
                )
            context.update({"git_sha": current_sha, "ci": ci})
            if gate == "hardware":
                context["physical_hardware"] = self.manifest["promotion"]["physical_hardware"]
        else:
            raise AgentEnvError("gate must be plan, pr, merge, or hardware")
        return sha256_json(context), context

    def approval_count(self, gate: str) -> int:
        path = self.approvals_path / gate
        if not path.is_dir():
            return 0
        current_digest, _ = self._approval_context(gate)
        count = 0
        for approval_path in path.glob("*.json"):
            approval = load_json(approval_path)
            if approval.get("context_sha256") == current_digest:
                count += 1
        return count

    def _archive_stale_approval(self, source: Path, gate: str) -> None:
        stamp = utc_now().replace(":", "").replace("+00:00", "Z")
        destination = self.path / "approval-history" / stamp / gate / source.name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), destination)

    def invalidate_gates(self, gates: set[str], *, event: str) -> None:
        status = self.status
        epochs = dict(status.get("gate_epochs", {}))
        for gate in gates:
            epochs[gate] = int(epochs.get(gate, 0)) + 1
        self.update_status({"gate_epochs": epochs}, event=event)

    def add_approval(self, gate: str, actor: str | None = None, note: str = "") -> tuple[int, int]:
        gate = gate.lower()
        allowed = {
            "plan": {"PLANNED"}, "pr": {"PR_READY"},
            "merge": {"CI_VERIFIED"}, "hardware": {"CI_VERIFIED", "MERGE_APPROVED"},
        }
        if gate not in allowed:
            raise AgentEnvError("gate must be plan, pr, merge, or hardware")
        status = self.status
        if status["state"] not in allowed[gate]:
            raise AgentEnvError(f"gate '{gate}' cannot be approved while state is {status['state']}")
        threshold = {
            "plan": int(self.policy["plan_approvals"]), "pr": 1,
            "merge": int(self.policy["merge_approvals"]), "hardware": int(self.policy["hardware_approvals"]),
        }[gate]
        if gate == "hardware" and threshold == 0:
            raise AgentEnvError("hardware approval is not applicable to this risk class")
        identity = safe_actor(actor)
        context_digest, context = self._approval_context(gate)
        gate_dir = self.approvals_path / gate
        gate_dir.mkdir(parents=True, exist_ok=True)
        target = gate_dir / f"{identity}.json"
        if target.exists():
            existing = load_json(target)
            if existing.get("context_sha256") == context_digest:
                raise AgentEnvError(f"{identity} already approved the current '{gate}' gate context")
            self._archive_stale_approval(target, gate)
        approval = {
            "schema_version": 1, "work_item": self.work_id, "gate": gate,
            "actor": identity, "timestamp": utc_now(), "note": note,
            "state": status["state"], "context_sha256": context_digest,
            "context": context,
            "artifact_sha256": {
                path.name: sha256_file(path) for path in sorted(self.artifacts_path.glob("*")) if path.is_file()
            },
        }
        atomic_write_json(target, approval)
        count = self.approval_count(gate)
        self._append_trace("human_approval_recorded", status["state"], status["state"], {
            "gate": gate, "count": count, "required": threshold, "context_sha256": context_digest
        }, actor=identity)
        if count >= threshold and gate == "plan":
            self.transition("PLANNED", "PLAN_APPROVED", event="plan_gate_satisfied")
        if count >= threshold and gate == "merge":
            self.transition("CI_VERIFIED", "MERGE_APPROVED", event="merge_gate_satisfied")
        self.refresh_evidence_index()
        return count, threshold

    def pr_is_approved(self) -> bool:
        try:
            return self.approval_count("pr") >= 1
        except AgentEnvError:
            return False

    def record_ci(self, status_value: str, url: str, commit: str | None = None) -> None:
        value = status_value.lower()
        if value not in {"passed", "failed"}:
            raise AgentEnvError("CI status must be passed or failed")
        current = self.status["state"]
        if current not in {"PR_READY", "CI_VERIFIED", "BLOCKED"}:
            raise AgentEnvError(f"cannot record CI while state is {current}")
        current_sha = git_sha(self.repo)
        recorded_commit = commit or current_sha
        if recorded_commit != current_sha:
            raise AgentEnvError(
                f"CI commit {recorded_commit} does not match current worktree HEAD {current_sha}"
            )
        self.invalidate_gates({"merge", "hardware"}, event="ci_context_changed")
        self.update_status({"ci": {
            "status": value, "url": url, "commit": recorded_commit, "recorded_at": utc_now()
        }}, event="ci_result_recorded")
        current = self.status["state"]
        if value == "passed" and current != "CI_VERIFIED":
            self.transition({"PR_READY", "BLOCKED"}, "CI_VERIFIED", event="ci_gate_satisfied")
        elif value == "failed" and current != "BLOCKED":
            self.transition({"PR_READY", "CI_VERIFIED"}, "BLOCKED", event="ci_gate_failed", error="CI failed")

    def record_promotion(self, level: str, evidence: str, actor: str | None = None) -> None:
        if self.status["state"] != "MERGE_APPROVED":
            raise AgentEnvError("promotion requires MERGE_APPROVED state")
        level = level.lower()
        if level not in {"simulation", "hil", "physical"}:
            raise AgentEnvError("promotion level must be simulation, hil, or physical")
        if level in {"hil", "physical"}:
            if self.manifest["promotion"]["physical_hardware"] != "human-approved":
                raise AgentEnvError("physical/HIL promotion is prohibited by the manifest")
            required = int(self.policy["hardware_approvals"])
            if self.approval_count("hardware") < required:
                raise AgentEnvError(f"physical/HIL promotion requires {required} distinct hardware approvals")
        identity = safe_actor(actor)
        promotion = {"level": level, "evidence": evidence, "actor": identity, "timestamp": utc_now(), "git_sha": git_sha(self.repo)}
        self.update_status({"promotion": promotion}, event="promotion_recorded")
        self.transition("MERGE_APPROVED", "PROMOTED", event="promotion_gate_satisfied")

    def close(self, actor: str | None = None, note: str = "") -> None:
        if self.status["state"] != "PROMOTED":
            raise AgentEnvError("work item can close only after promotion")
        identity = safe_actor(actor)
        self.write_artifact("closure.md", f"# Closure\n\nActor: {identity}\n\n{note}")
        self.transition("PROMOTED", "CLOSED", event="work_item_closed")

    def recover(self, target: str, actor: str | None = None, note: str = "") -> None:
        allowed_targets = {"INTAKE", "PLANNED", "PLAN_APPROVED", "IMPLEMENTED", "LOCALLY_VERIFIED", "ENV_VERIFIED", "REVIEWED", "PR_READY", "DIAGNOSING"}
        if target not in allowed_targets:
            raise AgentEnvError(f"recovery target is not allowed: {target}")
        current = self.status["state"]
        if current not in TRANSIENT_STATES | {"BLOCKED", "DIAGNOSED"}:
            raise AgentEnvError(f"recovery is not allowed from state {current}")
        identity = safe_actor(actor)
        if target in {"INTAKE", "PLANNED"}:
            self.invalidate_gates({"plan", "pr", "merge", "hardware"}, event="recovery_invalidated_all_gates")
        elif target in {"PLAN_APPROVED", "IMPLEMENTED", "LOCALLY_VERIFIED", "ENV_VERIFIED", "REVIEWED"}:
            self.invalidate_gates({"pr", "merge", "hardware"}, event="recovery_invalidated_downstream_gates")
        self._append_trace("manual_recovery_requested", current, target, {"note": note}, actor=identity)
        self.transition(current, target, event="manual_recovery_applied")

    def refresh_evidence_index(self) -> None:
        if not self.path.exists():
            return
        files: list[dict[str, Any]] = []
        for path in sorted(self.path.rglob("*")):
            if not path.is_file() or path in {self.lock_path, self.evidence_index_path}:
                continue
            files.append({"path": str(path.relative_to(self.path)), "size": path.stat().st_size, "sha256": sha256_file(path)})
        atomic_write_json(self.evidence_index_path, {
            "schema_version": 1, "work_item": self.work_id, "generated_at": utc_now(), "files": files
        })


def _path_matches(path: str, pattern: str) -> bool:
    path = path.lstrip("./")
    pattern = pattern.lstrip("./")
    if pattern in {"*", "**", "**/*"}:
        return True
    if path == pattern:
        return True
    if pattern.endswith("/**"):
        prefix = pattern[:-3].rstrip("/")
        return path == prefix or path.startswith(prefix + "/")
    return fnmatch.fnmatchcase(path, pattern)
