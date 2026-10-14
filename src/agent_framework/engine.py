"""ECP lifecycle and exact-candidate acceptance gates, owned by the controller."""

from __future__ import annotations

from contextlib import ExitStack
from dataclasses import asdict
from pathlib import Path
import tempfile
import uuid
from typing import Any

from .common import (
    Conflict,
    FrameworkError,
    RoleOutputRejected,
    bytes_digest,
    canonical,
    contained,
    digest,
    identifier,
    locked,
    read_json,
    write_json,
)
from .contracts import validate, validate_blueprint, validate_plan
from .environments import Environments
from .execution import ExecutionRequest, capture_execution
from .failures import classify
from .policy import (
    approval_count,
    in_scope,
    needs_safety,
    permissions,
    registry,
    risk_floor,
    transition,
)
from .roles import Roles
from .scm import Repository, validate_trace
from .store import Store
from .test_artifacts import development_hashes, materialize


def uid(prefix: str) -> str:
    return prefix + "-" + uuid.uuid4().hex.upper()


class Engine:
    def __init__(
        self, repo: Repository, store: Store, environments: Environments, work_id: str
    ):
        self.repo, self.store, self.environments = repo, store, environments
        self.work_id = identifier(work_id)
        if store.root.is_relative_to(
            repo.path
        ) or environments.store.root.is_relative_to(repo.path):
            raise FrameworkError(
                "controller and environment state must be outside the product checkout"
            )
        if store.exists(self.work_id):
            saved = store.get(self.work_id)["payload"]
            if "checkout" in saved:
                if str(repo.path) not in {
                    saved["source_repository"],
                    saved["checkout"],
                }:
                    raise FrameworkError(
                        "this work item belongs to a different repository"
                    )
                self.repo = Repository(Path(saved["checkout"]))
        self.roles = Roles(store, self.repo, environments)

    @property
    def lockfile(self) -> Path:
        return self.store.root / "controller.lock"

    @property
    def work(self) -> dict[str, Any]:
        return self.store.resolve(self.store.ref(self.work_id), current=True)["payload"]

    def new(
        self, request: str, *, intake_permissions: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        if not request.strip() or not self.repo.clean():
            raise FrameworkError("new work requires a request and a clean checkout")
        intake_permissions = (
            intake_permissions or registry()["default_execution_permissions"]
        )
        permissions(intake_permissions)
        with locked(self.lockfile), self.store.transaction():
            if any(
                self.store.get(x["id"])["payload"]["state"]
                not in {"PROMOTED", "CLOSED"}
                for x in self.store.list("work")
            ):
                raise Conflict("one active work item per product checkout")
            request_ref = self.store.publish(
                self.work_id + "-REQUEST", "request", "human", {"text": request}
            )
            return self.store.publish(
                self.work_id,
                "work",
                "framework",
                {
                    "state": "INTAKE",
                    "base_sha": self.repo.head,
                    "source_repository": str(self.repo.path),
                    "request": request_ref,
                    "intake_permissions": intake_permissions,
                    "failures": [],
                    "results": [],
                    "reviews": {},
                    "approvals": [],
                    "release_approvals": [],
                },
            )

    def _save(self, value: dict[str, Any]) -> dict[str, Any]:
        return self.store.publish(
            self.work_id,
            "work",
            "framework",
            value,
            expected_revision=self.store.head(self.work_id)["revision"],
        )

    def _advance(self, value: dict[str, Any], event: str, actor: str) -> dict[str, Any]:
        value = {**value, "state": transition(value["state"], event, actor)}
        self._save(value)
        self.store.event(
            "work_transition",
            {
                "work": self.work_id,
                "event": event,
                "actor": actor,
                "state": value["state"],
            },
        )
        return value

    def _need(self, *states: str) -> dict[str, Any]:
        work = self.work
        if work["state"] not in states:
            raise Conflict("operation is not available in " + work["state"])
        return work

    def _current(self, ref: dict[str, Any], kind: str | None = None) -> dict[str, Any]:
        record = self.store.resolve(ref, current=True)
        if kind and record["kind"] != kind:
            raise FrameworkError("unexpected artifact kind: " + record["kind"])
        return record["payload"]

    def _publish(
        self,
        suffix: str,
        kind: str,
        owner: str,
        payload: Any,
        dependencies: list[tuple[str, str]],
    ) -> dict[str, Any]:
        key = self.work_id + "-" + suffix
        return self.store.publish(
            key,
            kind,
            owner,
            payload,
            dependencies,
            expected_revision=(
                self.store.head(key)["revision"] if self.store.exists(key) else 0
            ),
        )

    def propose(
        self, blueprint: dict[str, Any], plan: dict[str, Any], consequences: list[str],
        *, _expected_work: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with locked(self.lockfile), self.store.transaction():
            work = self.work
            if work["state"] in {"PROMOTED", "CLOSED"}:
                raise Conflict("create new work to change a promoted project")
            if _expected_work is not None:
                self._role_guard(_expected_work, 'planner')
            previous = (
                self.store.get(work["blueprint"]["id"], work["blueprint"]["revision"])[
                    "payload"
                ]
                if "blueprint" in work
                else (
                    self.store.get("PROJECT-BLUEPRINT")["payload"]
                    if self.store.exists("PROJECT-BLUEPRINT")
                    else None
                )
            )
            validate_blueprint(blueprint, previous)
            validate_plan(plan, blueprint)
            if int(plan["risk_class"][1]) < int(
                risk_floor(plan["permissions"], consequences)[1]
            ):
                raise FrameworkError(
                    "Plan risk is below its consequence-derived minimum"
                )
            permissions(plan["permissions"])
            element_refs = []
            for group, kind in (
                ("requirements", "requirement"),
                ("components", "component"),
                ("interfaces", "interface"),
                ("verification_obligations", "verification_obligation"),
            ):
                for element in blueprint[group]:
                    key = element["id"]
                    if (
                        self.store.exists(key)
                        and self.store.get(key)["payload"] == element
                    ):
                        ref = self.store.ref(key)
                    else:
                        ref = self.store.publish(
                            key,
                            kind,
                            "planner",
                            element,
                            expected_revision=(
                                self.store.head(key)["revision"]
                                if self.store.exists(key)
                                else 0
                            ),
                        )
                    element_refs.append(ref)
            project_file = self.repo.path / "project.json"
            if (
                project_file.exists()
                and read_json(project_file)["project_id"] != blueprint["project_id"]
            ):
                raise FrameworkError(
                    "Blueprint project ID differs from the neutral project envelope"
                )
            bp_ref = self.store.publish(
                "PROJECT-BLUEPRINT",
                "blueprint",
                "planner",
                blueprint,
                [(x["id"], "derived_from") for x in element_refs],
                expected_revision=(
                    self.store.head("PROJECT-BLUEPRINT")["revision"]
                    if self.store.exists("PROJECT-BLUEPRINT")
                    else 0
                ),
            )
            plan_ref = self._publish(
                "PLAN", "plan", "planner", plan, [(bp_ref["id"], "derived_from")]
            )
            policy_ref = self._publish("POLICY", "policy", "framework", registry(), [])
            draft = self._publish(
                "DRAFT",
                "draft_package",
                "planner",
                {
                    "blueprint_ref": bp_ref,
                    "plan_ref": plan_ref,
                    "policy_ref": policy_ref,
                    "request_ref": work["request"],
                    "consequences": consequences,
                },
                [
                    (x["id"], "derived_from")
                    for x in (bp_ref, plan_ref, policy_ref, work["request"])
                ],
            )
            if work.get("candidate") and self.repo.clean():
                prior_candidate = self.store.resolve(work["candidate"])["payload"]
                if self.repo.head == prior_candidate["sha"]:
                    work["implementation_head"] = self.repo.head
                    work["prior_implementation_trace"] = prior_candidate["trace"]["changes"]
            work.update(
                {
                    "state": "DRAFT",
                    "blueprint": bp_ref,
                    "plan": plan_ref,
                    "policy": policy_ref,
                    "draft": draft,
                    "approvals": [],
                    "release_approvals": [],
                    "results": [],
                    "reviews": {},
                }
            )
            for key in (
                "package",
                "suite",
                "test_design_job",
                "test_design_suite",
                "bindings",
                "provider_feasibility",
                "tester_feasibility",
                "coder_feasibility",
                "candidate",
                "acceptance",
                "promotion",
                "subject",
                "subject_acceptance",
                "ci",
                "pull_request",
            ):
                work.pop(key, None)
            self._save(work)
            self.store.event(
                "semantic_package_revision",
                {"work": self.work_id, "draft": draft, "approval_required": True},
            )
            return draft

    def provider_preflight(self, selections: dict[str, str]) -> dict[str, Any]:
        with locked(self.lockfile), self.store.transaction():
            work = self._need("DRAFT")
            blueprint = self._current(work["blueprint"])
            if set(selections) != {
                r["id"] for r in blueprint["environment_requirements"]
            }:
                raise FrameworkError(
                    "select one environment generation for every requirement"
                )
            bindings = {}
            for requirement in blueprint["environment_requirements"]:
                try:
                    resolution = self.environments.preflight(
                        requirement,
                        selections[requirement["id"]],
                        work["intake_permissions"],
                    )
                    if not resolution["feasible"]:
                        raise FrameworkError(
                            "provider feasibility failed: " + str(resolution)
                        )
                    env = self.environments.resolve(
                        requirement, selections[requirement["id"]]
                    )
                except FrameworkError as exc:
                    ref = self._publish(
                        "PROVIDER-FEASIBILITY",
                        "feasibility",
                        "framework",
                        {
                            "feasible": False,
                            "requirement": requirement,
                            "finding": str(exc),
                        },
                        [(work["draft"]["id"], "derived_from")],
                    )
                    self._replan(work, ref, [str(exc)])
                    return ref
                payload = {
                    "requirement": requirement,
                    "generation": env["id"],
                    "artifact_digest": env["artifact_digest"],
                    "provider_digest": env["provider_digest"],
                    "backend": env["backend"],
                    "resolver_receipt": resolution["receipt"],
                }
                bindings[requirement["id"]] = self._publish(
                    "BIND-" + requirement["id"],
                    "environment_binding",
                    "framework",
                    payload,
                    [(work["blueprint"]["id"], "constrains")],
                )
            ref = self._publish(
                "PROVIDER-FEASIBILITY",
                "feasibility",
                "framework",
                {"feasible": True, "bindings": bindings},
                [
                    (work["draft"]["id"], "derived_from"),
                    *[(x["id"], "executes_on") for x in bindings.values()],
                ],
            )
            work.update(bindings=bindings, provider_feasibility=ref)
            self._advance(work, "provider_feasible", "framework")
            return ref

    def _role_output(
        self, reference: dict[str, Any], role: str, inputs: list[dict[str, Any]]
    ) -> dict[str, Any]:
        record = self.store.resolve(reference, current=True)
        if record["kind"] != "role_output" or record["owner"] != role:
            raise FrameworkError("expected a controller-recorded isolated role output")
        value = record["payload"]
        if not all(x in value["inputs"] for x in inputs):
            raise Conflict("role output does not cover the current required inputs")
        validate("RoleOutput", value["output"])
        return value["output"]

    def _preflight_import(self, reference, owner, operation):
        before = self.work
        record = self.store.resolve(reference, current=True)
        if record['kind'] != 'role_output' or record['owner'] != owner:
            raise FrameworkError('expected a current controller-recorded ' + owner + ' output')
        try:
            return operation()
        except Conflict:
            raise
        except FrameworkError as exc:
            with locked(self.lockfile), self.store.transaction():
                self._role_guard(before, owner)
                self._replan(self.work, reference, [str(exc)])
            raise RoleOutputRejected(str(exc), reference) from exc

    def tester_preflight(self, suite_ref, role_ref):
        return self._preflight_import(role_ref, 'tester', lambda: self._tester_preflight(suite_ref, role_ref))

    def _tester_preflight(
        self, suite_ref: dict[str, Any], role_ref: dict[str, Any]
    ) -> None:
        with locked(self.lockfile), self.store.transaction():
            work = self._need("PROVIDER_FEASIBLE")
            tests = self._current(suite_ref, "suite")
            blueprint = self._current(work["blueprint"])
            mandatory = {
                x["id"] for x in blueprint["verification_obligations"] if x["required"]
            }
            if not mandatory <= set(tests["obligations"]):
                raise FrameworkError(
                    "test design omits required verification obligations"
                )
            tracked = self.repo.files(self.repo.head)
            plan = self._current(work["plan"])
            for ref in tests["cases"]:
                case = self._current(ref, "test_case")
                if not set(case['obligations']) <= {x['id'] for x in blueprint['verification_obligations']}:
                    raise FrameworkError('test case references an obligation outside the current Blueprint')
                if case["visibility"] == "independent" and case["path"] in tracked:
                    raise FrameworkError(
                        "independent test sources must not be tracked in the product checkout"
                    )
                if case["visibility"] == "development" and (
                    not in_scope(case["path"], plan["scope"])
                    or not any(
                        in_scope(case["path"], {"include": t["paths"], "exclude": []})
                        for t in plan["tasks"]
                    )
                ):
                    raise FrameworkError(
                        "development test materialization is outside the approved Plan scope"
                    )
            output = self._role_output(
                role_ref,
                "tester",
                [work["draft"], work["provider_feasibility"], suite_ref],
            )
            if (
                output["artifact_type"] != "testability"
                or output["test_design_ref"] != suite_ref
            ):
                raise FrameworkError("Tester preflight did not establish feasibility")
            if not output["feasible"]:
                self._replan(work, role_ref, output["findings"])
                return
            work.update(suite=suite_ref, tester_feasibility=role_ref)
            self._advance(work, "tester_feasible", "tester")

    def coder_preflight(self, role_ref: dict[str, Any]) -> None:
        return self._preflight_import(role_ref, 'coder', lambda: self._coder_preflight(role_ref))

    def _coder_preflight(self, role_ref: dict[str, Any]) -> None:
        with locked(self.lockfile), self.store.transaction():
            work = self._need("TESTER_FEASIBLE")
            output = self._role_output(
                role_ref, "coder", [work["draft"], work["tester_feasibility"]]
            )
            if (
                output["artifact_type"] != "implementation_feasibility"
                or output["package_ref"] != work["draft"]
                or output["handoff_ref"] != work["tester_feasibility"]
            ):
                raise FrameworkError(
                    "Coder feasibility is absent or references a different handoff"
                )
            if not output["feasible"]:
                self._replan(work, role_ref, output["findings"])
                return
            work["coder_feasibility"] = role_ref
            self._advance(work, "coder_feasible", "coder")

    def reconcile(self, role_ref: dict[str, Any]) -> dict[str, Any]:
        return self._preflight_import(role_ref, 'planner', lambda: self._reconcile(role_ref))

    def _reconcile(self, role_ref: dict[str, Any]) -> dict[str, Any]:
        with locked(self.lockfile), self.store.transaction():
            work = self._need("FEASIBLE")
            output = self._role_output(
                role_ref,
                "planner",
                [
                    work[x]
                    for x in (
                        "draft",
                        "provider_feasibility",
                        "tester_feasibility",
                        "coder_feasibility",
                    )
                ],
            )
            blueprint = self._current(work["blueprint"])
            plan = self._current(work["plan"])
            if (
                output["artifact_type"] != "planning"
                or output["blueprint_ref"] != work["blueprint"]
                or output["plan_ref"] != work["plan"]
                or set(output["requirement_reconciliation"])
                != {x["id"] for x in blueprint["requirements"]}
                or output["findings"]
            ):
                raise FrameworkError(
                    "Planner reconciliation is incomplete or has unresolved findings"
                )
            package = {
                "artifact_type": "engineering_change_package",
                "request_refs": [work["request"]],
                "blueprint_ref": work["blueprint"],
                "plan_ref": work["plan"],
                "provider_feasibility_ref": work["provider_feasibility"],
                "tester_feasibility_ref": work["tester_feasibility"],
                "coder_feasibility_ref": work["coder_feasibility"],
                "policy_ref": work["policy"],
                "test_design_ref": work["suite"],
                "scope_include": plan["scope"]["include"],
                "scope_exclude": plan["scope"]["exclude"],
                "permissions": plan["permissions"],
                "risk_class": plan["risk_class"],
                "delivery": plan["delivery"],
                "known_constraints": [],
            }
            validate("ChangePackage", package)
            deps = [
                work[x]
                for x in (
                    "draft",
                    "blueprint",
                    "plan",
                    "policy",
                    "provider_feasibility",
                    "tester_feasibility",
                    "coder_feasibility",
                    "suite",
                )
            ] + [role_ref]
            ref = self._publish(
                "PACKAGE",
                "package",
                "planner",
                package,
                [(x["id"], "approved_as_part_of") for x in deps],
            )
            work["package"] = ref
            self._advance(work, "reconciled", "planner")
            return ref

    def _replan(
        self, work: dict[str, Any], source: dict[str, Any], findings: list[str]
    ) -> dict[str, Any]:
        if not findings:
            raise FrameworkError("infeasibility requires a concrete explanation")
        ref = self.store.publish(
            uid("FEASIBILITY-FAILURE"),
            "failure",
            "framework",
            {
                "class": "feasibility_failure",
                "identity": digest({"source": source, "findings": findings}),
                "owner": "planner",
                "findings": findings,
                "automatic_retry_budget": 0,
                "result": source,
                "resume_state": work['state'],
            },
            [(source["id"], "derived_from")],
        )
        work["failures"].append(ref)
        work["state"] = "REPLAN_REQUIRED"
        self._save(work)
        return ref

    def approve(
        self, actor: str, expected_digest: str, *, release: bool = False, delivery: Any = None
    ) -> dict[str, Any]:
        actor = actor.strip().casefold()
        if not actor.strip():
            raise FrameworkError("an explicit approver identity is required")
        with locked(self.lockfile), self.store.transaction():
            work = self._need(
                *(("ACCEPTED", "CI_VERIFIED") if release else ("APPROVAL_READY",))
            )
            ref = work["acceptance"] if release else work["package"]
            self._current(ref)
            if ref["digest"] != expected_digest:
                raise Conflict("approval digest does not match the reviewable artifact")
            remote_review = None
            if release:
                self._gate(work)
                plan = self._current(work["plan"])
                if plan["delivery"] == "scm":
                    from .remote import delivery_for
                    adapter = delivery or delivery_for(self.repo, plan["scm"])
                    pr = self._current(work["pull_request"])
                    candidate_sha = self._current(work["candidate"])["sha"]
                    adapter.ci(pr, candidate_sha, plan["scm"]["required_checks"])
                    remote_review = adapter.review(pr, candidate_sha)
                    if remote_review["actor"].strip().casefold() != actor:
                        raise Conflict("release approver must match the verified remote human review")
            key = "release_approvals" if release else "approvals"
            if any(self._current(r)["actor"] == actor for r in work[key]):
                raise FrameworkError("the same person cannot count as two approvers")
            approval = self.store.publish(
                uid("APPROVAL"),
                "approval",
                "human",
                {
                    "actor": actor,
                    "subject": ref,
                    "purpose": "release" if release else "implementation",
                    "remote_review": remote_review,
                },
                [(ref["id"], "approved_as_part_of")],
            )
            work[key].append(approval)
            count = (
                approval_count(self._current(work["plan"])["risk_class"])
                if release
                else 1
            )
            if len(work[key]) >= count:
                event = "approve_package"
                if release:
                    plan = self._current(work["plan"])
                    if plan["delivery"] == "scm" and work["state"] != "CI_VERIFIED":
                        raise Conflict(
                            "SCM delivery requires recorded remote CI before merge approval"
                        )
                    event = (
                        "approve_merge"
                        if plan["delivery"] == "scm"
                        else "approve_artifact_release"
                    )
                self._advance(work, event, "human")
            else:
                self._save(work)
            return approval

    def start(self) -> dict[str, Any]:
        with locked(self.lockfile), self.store.transaction():
            work = self._need("APPROVED")
            self._package_gate(work)
            if not self.repo.clean():
                raise Conflict("start requires a clean checkout")
            expected_branch = "agent/" + self.work_id.lower()
            checkout = (
                self.store.root.parent
                / "worktrees"
                / digest(work["source_repository"])[:12]
                / self.work_id
            )
            if not checkout.exists():
                checkout.parent.mkdir(parents=True, exist_ok=True)
                self.repo.git(
                    "worktree",
                    "add",
                    "-b",
                    expected_branch,
                    str(checkout),
                    work["base_sha"],
                )
            candidate_repo = Repository(checkout)
            source_common = (
                self.repo.path / self.repo.git("rev-parse", "--git-common-dir").strip()
            ).resolve()
            candidate_common = (
                candidate_repo.path
                / candidate_repo.git("rev-parse", "--git-common-dir").strip()
            ).resolve()
            if (
                source_common != candidate_common
                or candidate_repo.head != work.get("implementation_head", work["base_sha"])
                or candidate_repo.branch() != expected_branch
                or not candidate_repo.clean()
            ):
                raise Conflict(
                    "existing worktree does not match this work item's clean baseline and branch"
                )
            self.repo = candidate_repo
            self.roles = Roles(self.store, self.repo, self.environments)
            work["checkout"] = str(checkout)
            self._advance(work, "start_implementation", "framework")
            return {
                "state": "IMPLEMENTING",
                "checkout": str(checkout),
                "branch": expected_branch,
            }

    def candidate(
        self,
        trace_changes: list[dict[str, Any]],
        *,
        subject: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        intent_path = None
        with locked(self.lockfile), self.store.transaction():
            work = self._need("IMPLEMENTING")
            self._package_gate(work)
            if self.repo.branch() != "agent/" + self.work_id.lower():
                raise Conflict("candidate is not on its work-item feature branch")
            plan = self._current(work["plan"])
            blueprint = self._current(work["blueprint"])
            protected = development_hashes(self.store, work["suite"])
            # Concrete development tests are materialized by the controller, not Coder.
            # Existing files must already match the Tester-owned bytes before replacement.
            for path, hashed in protected.items():
                target = contained(self.repo.path, path)
                head_files = self.repo.files(self.repo.head)
                unchanged = (
                    path in head_files
                    and self.repo.git("hash-object", "--", path).strip()
                    == head_files[path][1]
                    if target.exists()
                    else False
                )
                if (
                    target.exists()
                    and bytes_digest(target.read_bytes()) != hashed
                    and not unchanged
                ):
                    raise FrameworkError(
                        "Tester-owned repository file changed outside the test workflow: "
                        + path
                    )
            materialize(
                self.store, work["suite"], self.repo.path, include_independent=False
            )
            trace_changes = list(trace_changes)
            if any(c["path"] in protected for c in trace_changes):
                raise FrameworkError("Coder trace must not claim Tester-owned paths")
            traced = {x["path"] for x in trace_changes}
            tracked = self.repo.files(work["base_sha"])
            for case_ref in self._current(work["suite"])["cases"]:
                case = self._current(case_ref)
                if case["visibility"] == "independent":
                    if (self.repo.path / case["path"]).exists():
                        raise FrameworkError(
                            "independent sources appeared in the product checkout"
                        )
                    continue
                path = case["path"]
                if path in traced or (
                    path in tracked
                    and path not in self.repo.diff(work["base_sha"], self.repo.head)
                    and not self.repo.git("diff", "HEAD", "--", path)
                ):
                    continue
                tasks = [
                    t
                    for t in plan["tasks"]
                    if in_scope(path, {"include": t["paths"], "exclude": []})
                ]
                task = tasks[0]
                trace_changes.append(
                    {
                        "path": path,
                        "requirement_ids": task["requirements"],
                        "design_ids": task["design"],
                        "task_ids": [task["id"]],
                    }
                )

            def check_tree(tree: str) -> None:
                nonlocal intent_path, trace_changes
                actual_paths = set(self.repo.diff(work["base_sha"], tree))
                trace_changes = [c for c in trace_changes if c["path"] in actual_paths]
                preview = {
                    "role": "coder",
                    "artifact_type": "implementation_trace",
                    "candidate_sha": tree,
                    "package_ref": work["package"],
                    "changes": trace_changes,
                    "incomplete_obligations": [],
                }
                validate_trace(
                    self.repo,
                    work["base_sha"],
                    tree,
                    preview,
                    blueprint,
                    plan,
                    work["package"],
                )
                self.store.event(
                    "candidate_commit_intent",
                    {"work": self.work_id, "tree": tree, "trace": preview},
                )
                intent_path = self.store.root / ("candidate-intent-" + tree + ".json")
                write_json(
                    intent_path,
                    {
                        "work": self.work_id,
                        "expected_head": self.repo.head,
                        "base_sha": work["base_sha"],
                        "tree": tree,
                        "trace": preview,
                        "subject": subject or {},
                        "package": work["package"],
                    },
                )

            candidate_sha = self.repo.candidate(
                work["base_sha"],
                self.repo.head,
                plan["scope"],
                protected,
                "Implement " + self.work_id,
                check_tree,
            )
            trace = {
                "role": "coder",
                "artifact_type": "implementation_trace",
                "candidate_sha": candidate_sha,
                "package_ref": work["package"],
                "changes": trace_changes,
                "incomplete_obligations": [],
            }
            validate_trace(
                self.repo,
                work["base_sha"],
                candidate_sha,
                trace,
                blueprint,
                plan,
                work["package"],
            )
            ref = self._publish(
                "CANDIDATE",
                "candidate",
                "framework",
                {
                    "sha": candidate_sha,
                    "base_sha": work["base_sha"],
                    "trace": trace,
                    "subject": subject or {},
                },
                [(work["package"]["id"], "implements")],
            )
            work.update(
                candidate=ref,
                subject=subject or {},
                results=[],
                reviews={},
                release_approvals=[],
            )
            self._advance(work, "candidate_created", "framework")
        if intent_path:
            intent_path.unlink(missing_ok=True)
        return ref

    def pending_candidate_intents(self):
        work = self.work
        return [p for p in sorted(self.store.root.glob('candidate-intent-*.json'))
                if (value := read_json(p)).get('work') == self.work_id
                and value.get('package') == work.get('package')]

    def recover_candidate(self) -> dict[str, Any]:
        with locked(self.lockfile), self.store.transaction():
            work = self._need("IMPLEMENTING", "CANDIDATE")
            self._package_gate(work)
            if self.repo.branch() != 'agent/' + self.work_id.lower():
                raise Conflict('recovery requires the exact work-item checkout')
            pending = self.pending_candidate_intents()
            if not pending:
                raise Conflict('no candidate intent for the current approved work item')
            if not self.repo.clean():
                eligible = [(p, read_json(p)) for p in pending]
                eligible = [(p, v) for p, v in eligible if v['expected_head'] == self.repo.head]
                if len(eligible) != 1 or work['state'] != 'IMPLEMENTING':
                    raise Conflict('ambiguous or stale uncommitted candidate intent')
                path, intent = eligible[0]
                if intent['base_sha'] != work['base_sha']:
                    raise Conflict('candidate intent belongs to a different work-item baseline')
                def exact_tree(tree):
                    if tree != intent['tree']:
                        raise Conflict('checkout differs from the exact intended candidate tree')
                    validate_trace(self.repo, work['base_sha'], tree, intent['trace'],
                                   self._current(work['blueprint']), self._current(work['plan']), work['package'])
                self.repo.candidate(work['base_sha'], intent['expected_head'],
                                    self._current(work['plan'])['scope'],
                                    development_hashes(self.store, work['suite']),
                                    'Implement ' + self.work_id, exact_tree)
            tree = self.repo.git('rev-parse', 'HEAD^{tree}').strip()
            path = self.store.root / ('candidate-intent-' + tree + '.json')
            if path not in pending:
                raise Conflict('clean checkout does not match a current candidate intent')
            intent = read_json(path)
            if (
                intent["work"] != self.work_id
                or intent["package"] != work["package"]
                or intent["base_sha"] != work["base_sha"]
            ):
                raise Conflict("candidate intent belongs to different approved inputs")
            if self.repo.git("rev-parse", "HEAD^").strip() != intent["expected_head"]:
                raise Conflict("HEAD is not the single intended candidate commit")
            trace = {**intent["trace"], "candidate_sha": self.repo.head}
            validate_trace(
                self.repo,
                work["base_sha"],
                self.repo.head,
                trace,
                self._current(work["blueprint"]),
                self._current(work["plan"]),
                work["package"],
            )
            if work["state"] == "CANDIDATE":
                self._candidate_gate(work)
                ref = work["candidate"]
            else:
                ref = self._publish(
                    "CANDIDATE",
                    "candidate",
                    "framework",
                    {
                        "sha": self.repo.head,
                        "base_sha": work["base_sha"],
                        "trace": trace,
                        "subject": intent["subject"],
                    },
                    [(work["package"]["id"], "implements")],
                )
                work.update(
                    candidate=ref,
                    subject=intent["subject"],
                    results=[],
                    reviews={},
                    release_approvals=[],
                )
                self._advance(work, "candidate_created", "framework")
                self.store.event(
                    "candidate_recovered", {"candidate": ref, "tree": tree}
                )
        path.unlink(missing_ok=True)
        return ref

    def _package_gate(self, work: dict[str, Any]) -> None:
        self._current(work["package"], "package")
        self._current(work["suite"], "suite")
        if not work["approvals"]:
            raise Conflict("implementation approval is missing")
        for ref in work["approvals"]:
            if self._current(ref, "approval")["subject"] != work["package"]:
                raise Conflict("approval is bound to a different package")
        for ref in work["bindings"].values():
            binding = self._current(ref, "environment_binding")
            env = self.environments.resolve(
                binding["requirement"], binding["generation"]
            )
            receipt = self.environments.store.resolve(
                binding["resolver_receipt"], current=True
            )["payload"]
            if (
                not receipt["feasible"]
                or receipt["requirement"] != binding["requirement"]
                or receipt["generation"] != binding["generation"]
            ):
                raise Conflict("provider feasibility receipt is missing or stale")
            if (
                env["artifact_digest"] != binding["artifact_digest"]
                or env["provider_digest"] != binding["provider_digest"]
            ):
                raise Conflict("environment/provider binding changed")

    def _candidate_gate(self, work: dict[str, Any]) -> dict[str, Any]:
        self._package_gate(work)
        if self.repo.branch() != "agent/" + self.work_id.lower():
            raise Conflict("candidate is not on its work-item feature branch")
        candidate = self._current(work["candidate"], "candidate")
        if self.repo.head != candidate["sha"] or not self.repo.clean():
            raise Conflict("checkout no longer matches the exact clean candidate")
        validate_trace(
            self.repo,
            work["base_sha"],
            candidate["sha"],
            candidate["trace"],
            self._current(work["blueprint"]),
            self._current(work["plan"]),
            work["package"],
        )
        return candidate

    def verify(
        self, environment_id: str, action_id: str, *, final: bool = False
    ) -> dict[str, Any]:
        # Per-project lock serializes gate changes. Every execution still has isolated outputs.
        with locked(self.lockfile):
            work = self._need("ACCEPTING" if final else "CANDIDATE")
            candidate = self._candidate_gate(work)
            if environment_id not in work["bindings"]:
                raise FrameworkError("environment is outside the approved matrix")
            binding_ref = work["bindings"][environment_id]
            binding = self._current(binding_ref)
            blueprint = self._current(work["blueprint"])
            obligations = (
                blueprint["final_acceptance"]["obligations"]
                if final
                else [
                    x["id"]
                    for x in blueprint["verification_obligations"]
                    if x["required"]
                ]
            )
            run_id = uid("RUN")
            with (
                self.environments.lease(binding["generation"], run_id) as env,
                tempfile.TemporaryDirectory(
                    prefix="verify-", dir=self.store.root
                ) as tmp,
            ):
                backend = self.environments.backend(env["backend"])
                if not backend.authoritative:
                    raise FrameworkError(
                        "host/advisory execution cannot satisfy required verification"
                    )
                provider = self.environments.provider(env["provider_id"])
                actions = [x for x in provider["actions"] if x["id"] == action_id]
                if len(actions) != 1:
                    raise FrameworkError("unknown provider verification action")
                action = actions[0]
                permissions(
                    action["permissions"], self._current(work["plan"])["permissions"]
                )
                root = Path(tmp)
                project = root / "project"
                output = root / "output"
                tests = root / "tests"
                ctx = root / "context"
                output.mkdir()
                tests.mkdir()
                ctx.mkdir()
                self.repo.snapshot(candidate["sha"], project)
                materialize(self.store, work["suite"], tests, include_independent=True)
                input_value = {
                    "schema_version": 1,
                    "run_id": run_id,
                    "candidate_sha": candidate["sha"],
                    "package_ref": work["package"],
                    "suite_ref": work["suite"],
                    "environment_id": environment_id,
                    "environment_generation": env["id"],
                    "obligations": obligations,
                    "purpose": "final_acceptance" if final else "targeted",
                    "subject": work["subject"],
                }
                write_json(ctx / "input.json", input_value, 0o644)
                execution = capture_execution(
                    backend,
                    ExecutionRequest(
                        env["artifact_digest"],
                        action["argv"],
                        project,
                        output,
                        action["timeout_seconds"],
                        action["permissions"]["network"] != "none",
                        read_only={
                            "/context": ctx,
                            "/tests": tests,
                            **self.environments.credentials(
                                action["permissions"]["credentials"]
                            ),
                        },
                    ),
                )
                log = self.store.blob(
                    (
                        execution.process.stdout + "\n" + execution.process.stderr
                    ).encode()
                )
                report = None
                try:
                    report_path = contained(output, "result.json")
                    if (
                        not report_path.is_file()
                        or report_path.stat().st_size > 4 * 1024 * 1024
                    ):
                        raise FrameworkError("missing/oversized provider report")
                    report = read_json(report_path)
                    if not isinstance(report, dict) or set(report) != {
                        "schema_version",
                        "status",
                        "candidate_evaluated",
                        "test_count",
                        "obligation_ids",
                        "failure_stage",
                    }:
                        raise FrameworkError(
                            "provider report contains untrusted identity fields or unknown keys"
                        )
                except (FrameworkError, OSError):
                    report = {
                        "schema_version": 1,
                        "status": "provider_failure",
                        "candidate_evaluated": False,
                        "test_count": 0,
                        "obligation_ids": obligations,
                        "failure_stage": "collect",
                    }
                if (
                    not execution.prepared
                    or execution.artifact_digest != env["artifact_digest"]
                    or execution.backend != backend.name
                ):
                    report.update(
                        status="environment_failure",
                        candidate_evaluated=False,
                        test_count=0,
                        failure_stage="prepare",
                    )
                elif execution.process.timed_out or execution.process.output_limited:
                    report.update(
                        status="unknown_failure",
                        candidate_evaluated=False,
                        test_count=0,
                        failure_stage="execute",
                    )
                elif execution.process.returncode and report["status"] == "passed":
                    report.update(
                        status="provider_failure",
                        candidate_evaluated=False,
                        test_count=0,
                        failure_stage="collect",
                    )
                result = {
                    **report,
                    "run_id": run_id,
                    "candidate_sha": candidate["sha"],
                    "provider_digest": env["provider_digest"],
                    "environment_generation": env["id"],
                    "environment_artifact_digest": env["artifact_digest"].removeprefix(
                        "sha256:"
                    ),
                    "suite_digest": work["suite"]["digest"],
                    "evidence": [log, self.store.blob(canonical(input_value))],
                }
                try:
                    validate("ProviderResult", result)
                    if set(result["obligation_ids"]) != set(obligations):
                        raise FrameworkError(
                            "provider did not execute the required obligations"
                        )
                except FrameworkError:
                    result.update(
                        schema_version=1,
                        status="provider_failure",
                        candidate_evaluated=False,
                        test_count=0,
                        obligation_ids=obligations,
                        failure_stage="classify",
                    )
                    validate("ProviderResult", result)
                with self.store.transaction():
                    # Refuse stale output even after a successful process.
                    self._candidate_gate(work)
                    ref = self.store.publish(
                        run_id,
                        "verification_result",
                        "framework",
                        {
                            "result": result,
                            "purpose": input_value["purpose"],
                            "environment_id": environment_id,
                            "execution_id": execution.execution_id,
                            "backend": execution.backend,
                            "input_digest": digest(input_value),
                            "process": {
                                k: v
                                for k, v in asdict(execution.process).items()
                                if k not in {"stdout", "stderr"}
                            },
                        },
                        [
                            (work["candidate"]["id"], "verifies"),
                            (work["suite"]["id"], "derived_from"),
                            (binding_ref["id"], "executes_on"),
                        ],
                    )
                    work["results"].append(ref)
                    if result["status"] != "passed":
                        self._fail(
                            work,
                            result["status"],
                            obligations,
                            {
                                "candidate": candidate["sha"],
                                "suite": work["suite"]["digest"],
                                "generation": env["id"],
                            },
                            ref,
                        )
                    else:
                        self._save(work)
                    return ref

    def _matrix(self, work: dict[str, Any], final: bool, *, only_environment=None) -> list[dict[str, Any]]:
        candidate = self._candidate_gate(work)
        bp = self._current(work["blueprint"])
        envs = (
            bp["final_acceptance"]["required_environments"]
            if final
            else list(work["bindings"])
        )
        obligations = set(
            bp["final_acceptance"]["obligations"]
            if final
            else [x["id"] for x in bp["verification_obligations"] if x["required"]]
        )
        if only_environment is not None:
            if only_environment not in envs:
                raise Conflict("environment is not part of the required matrix")
            envs = [only_environment]
        selected = []
        for environment_id in envs:
            binding = self._current(work["bindings"][environment_id])
            matching = []
            for ref in work["results"]:
                if self.store.head(ref["id"])["state"] != "CURRENT":
                    continue
                value = self._current(ref, "verification_result")
                r = value["result"]
                if (
                    value["purpose"] == ("final_acceptance" if final else "targeted")
                    and value["environment_id"] == environment_id
                    and r["candidate_sha"] == candidate["sha"]
                    and r["suite_digest"] == work["suite"]["digest"]
                    and r["environment_generation"] == binding["generation"]
                    and r["environment_artifact_digest"]
                    == binding["artifact_digest"].removeprefix("sha256:")
                    and r["provider_digest"] == binding["provider_digest"]
                ):
                    matching.append((ref, r))
            if (
                not matching
                or matching[-1][1]["status"] != "passed"
                or not obligations <= set(matching[-1][1]["obligation_ids"])
            ):
                raise Conflict(
                    "required passing evidence is missing for " + environment_id
                )
            selected.append(matching[-1][0])
        return selected

    def verified(self, tester_ref: dict[str, Any]) -> None:
        with locked(self.lockfile), self.store.transaction():
            work = self._need("CANDIDATE")
            results = self._matrix(work, False)
            verdict = self._role_output(
                tester_ref, "tester", [work["candidate"], *results]
            )
            if (
                verdict["artifact_type"] != "verification"
                or verdict["candidate_sha"] != self._current(work["candidate"])["sha"]
                or not all(x in verdict["result_refs"] for x in results)
            ):
                raise FrameworkError(
                    "Tester verdict does not establish current targeted verification"
                )
            if verdict["verdict"] != "passed":
                self._fail(
                    work,
                    "unknown_failure",
                    verdict["obligation_ids"],
                    {
                        "candidate": self._current(work["candidate"])["sha"],
                        "suite": work["suite"]["digest"],
                    },
                    tester_ref,
                )
                return
            work["tester_verdict"] = tester_ref
            self._advance(work, "targeted_verified", "tester")

    def review(self, reference: dict[str, Any]) -> None:
        with locked(self.lockfile), self.store.transaction():
            work = self._need("VERIFIED")
            candidate = self._candidate_gate(work)
            name = self.store.resolve(reference, current=True)["owner"]
            if name not in {"reviewer", "safety_reviewer"}:
                raise FrameworkError("review requires a Reviewer or Safety Reviewer")
            value = self._role_output(
                reference,
                name,
                [work["candidate"], work["package"], work["tester_verdict"]],
            )
            if (
                value["candidate_sha"] != candidate["sha"]
                or value["package_ref"] != work["package"]
            ):
                raise Conflict("review has mismatched candidate/package bindings")
            if value["verdict"] != "approved" or value["findings"]:
                self._fail(
                    work,
                    value.get("failure_class", "unknown_failure"),
                    [x["id"] for x in self._current(work["blueprint"])["requirements"]],
                    {"candidate": candidate["sha"], "suite": work["suite"]["digest"]},
                    reference,
                )
                return
            work["reviews"][name] = reference
            required = {"reviewer"} | (
                {"safety_reviewer"}
                if needs_safety(self._current(work["plan"])["risk_class"])
                else set()
            )
            if required <= work["reviews"].keys():
                self._advance(work, "reviews_complete", "framework")
            else:
                self._save(work)

    def accepting(self) -> None:
        with locked(self.lockfile), self.store.transaction():
            work = self._need("REVIEWED")
            self._gate(work, require_final=False)
            self._advance(work, "readiness_validated", "framework")

    def accept(self) -> dict[str, Any]:
        with locked(self.lockfile), self.store.transaction():
            work = self._need("ACCEPTING")
            self._gate(work)
            results = self._matrix(work, True)
            candidate = self._current(work["candidate"])
            payload = {
                "candidate_sha": candidate["sha"],
                "package_ref": work["package"],
                "suite_ref": work["suite"],
                "environment_generations": sorted(
                    {self._current(r)["generation"] for r in work["bindings"].values()}
                ),
                "result_refs": results,
                "purpose": "final_acceptance",
                "execution_kind": "provider_environment",
                "input_digests": sorted(
                    {self._current(r)["input_digest"] for r in results}
                ),
            }
            validate("EvidenceBinding", payload)
            ref = self._publish(
                "ACCEPTANCE",
                "acceptance",
                "framework",
                payload,
                [
                    (r["id"], "derived_from")
                    for r in [
                        work["candidate"],
                        work["suite"],
                        *results,
                        *work["reviews"].values(),
                        *(
                            [work["subject_acceptance"]]
                            if "subject_acceptance" in work
                            else []
                        ),
                    ]
                ],
            )
            work["acceptance"] = ref
            self._advance(work, "final_acceptance_passed", "tester")
            return ref

    def _gate(self, work: dict[str, Any], *, require_final: bool = True) -> None:
        self._candidate_gate(work)
        self._matrix(work, False)
        if "environment_release" in self._current(work["plan"]):
            if "subject_acceptance" not in work:
                raise Conflict(
                    "the built provider/environment subject has not passed acceptance"
                )
            receipt = self._current(
                work["subject_acceptance"], "environment_acceptance"
            )
            if (
                receipt["subject"] != work["subject"]
                or receipt["candidate_sha"] != self._current(work["candidate"])["sha"]
                or receipt["status"] != "passed"
                or receipt["test_count"] < 1
            ):
                raise Conflict(
                    "provider/environment acceptance does not match the release subject"
                )
        self._current(work["tester_verdict"], "role_output")
        required = {"reviewer"} | (
            {"safety_reviewer"}
            if needs_safety(self._current(work["plan"])["risk_class"])
            else set()
        )
        if not required <= work["reviews"].keys():
            raise Conflict("required candidate reviews are missing")
        for ref in work["reviews"].values():
            self._current(ref, "role_output")
        if require_final:
            self._matrix(work, True)

    def publish_pull_request(
        self, actor: str, title: str, body: str, *, delivery: Any = None
    ) -> dict[str, Any]:
        if not actor.strip():
            raise FrameworkError(
                "remote publication requires an explicit operator identity"
            )
        from .remote import delivery_for

        with locked(self.lockfile), self.store.transaction():
            work = self._need("ACCEPTED")
            self._gate(work)
            plan = self._current(work["plan"])
            if plan["delivery"] != "scm":
                raise Conflict("the ECP does not authorize SCM delivery")
            value = (delivery or delivery_for(self.repo, self._current(work["plan"])["scm"])).publish(
                self._current(work["candidate"])["sha"],
                plan["scm"]["base_branch"],
                title,
                body,
            )
            ref = self._publish(
                "PR",
                "pull_request",
                "framework",
                {**value, "actor": actor},
                [(work["acceptance"]["id"], "derived_from")],
            )
            work["pull_request"] = ref
            self._advance(work, "publish_pull_request", "framework")
            return ref

    def sync_remote_review(self, *, delivery=None):
        from .remote import delivery_for
        work = self._need("CI_VERIFIED")
        plan = self._current(work["plan"])
        adapter = delivery or delivery_for(self.repo, plan["scm"])
        review = adapter.review(self._current(work["pull_request"]), self._current(work["candidate"])["sha"])
        return self.approve(review["actor"], work["acceptance"]["digest"], release=True, delivery=adapter)

    def record_ci(self, *, delivery: Any = None) -> dict[str, Any]:
        from .remote import delivery_for

        with locked(self.lockfile), self.store.transaction():
            work = self._need("PR_OPEN")
            self._gate(work)
            value = (delivery or delivery_for(self.repo, self._current(work["plan"])["scm"])).ci(
                self._current(work["pull_request"]),
                self._current(work["candidate"])["sha"],
                self._current(work["plan"])["scm"]["required_checks"],
            )
            ref = self._publish(
                "CI",
                "ci",
                "framework",
                value,
                [
                    (work["pull_request"]["id"], "verifies"),
                    (work["candidate"]["id"], "verifies"),
                ],
            )
            work["ci"] = ref
            self._advance(work, "ci_recorded", "framework")
            return ref

    def promote(
        self, *, remote_authorized: bool = False, delivery: Any = None
    ) -> dict[str, Any]:
        with locked(self.lockfile), ExitStack() as stack:
            work = self._need("RELEASE_APPROVED")
            for ref in work["bindings"].values():
                stack.enter_context(
                    self.environments.lease(
                        self._current(ref)["generation"], "promotion:" + self.work_id
                    )
                )
            with self.store.transaction():
                self._gate(work)
                self._current(work["acceptance"], "acceptance")
                actors = {
                    self._current(x, "approval")["actor"]
                    for x in work["release_approvals"]
                    if self._current(x)["subject"] == work["acceptance"]
                }
                if len(actors) < approval_count(
                    self._current(work["plan"])["risk_class"]
                ):
                    raise Conflict("release approvals are missing or stale")
                remote = None
                if self._current(work["plan"])["delivery"] == "scm":
                    if not remote_authorized:
                        raise FrameworkError(
                            "SCM promotion requires --authorize-remote"
                        )
                    from .remote import delivery_for

                    self._current(work["ci"])
                    remote = (delivery or delivery_for(self.repo, self._current(work["plan"])["scm"])).promote(
                        self._current(work["pull_request"]),
                        self._current(work["candidate"])["sha"],
                        self._current(work["plan"])["scm"]["required_checks"],
                    )
                ref = self._publish(
                    "PROMOTION",
                    "promotion",
                    "framework",
                    {
                        "candidate_sha": self._current(work["candidate"])["sha"],
                        "acceptance": work["acceptance"],
                        "subject": work["subject"],
                        "delivery": self._current(work["plan"])["delivery"],
                        "remote_promotion": remote,
                    },
                    [
                        (x["id"], "approved_as_part_of")
                        for x in [work["acceptance"], *work["release_approvals"]]
                    ],
                )
                work["promotion"] = ref
                self._advance(work, "promote", "framework")
                return ref

    def release_proof(self) -> dict[str, Any]:
        work = self._need("PROMOTED", "CLOSED")
        proof = self._current(work["promotion"], "promotion")
        return {
            **proof,
            "promotion_ref": work["promotion"],
            "source_project": str(self.repo.path),
        }

    def close(self) -> None:
        with locked(self.lockfile), self.store.transaction():
            self._advance(self._need("PROMOTED"), "close", "framework")

    def recover_role(self):
        from .worktree_apply import recover
        with locked(self.lockfile):
            return {'recovered': recover(self.store, self.repo)}

    def run_role(self, name, generation, action_id, *, suite_ref=None, receipt_id=None):
        before = self.work
        try:
            return self._prepare_role(name, generation, action_id, suite_ref=suite_ref, receipt_id=receipt_id)()
        except RoleOutputRejected as exc:
            with locked(self.lockfile), self.store.transaction():
                self._role_guard(before, name)
                work = self.work
                if name in {'planner', 'tester', 'coder'} and work['state'] in {'INTAKE', 'REPLAN_REQUIRED', 'PROVIDER_FEASIBLE', 'TESTER_FEASIBLE', 'FEASIBLE'}:
                    self._replan(work, exc.reference, [str(exc)])
                elif name == 'coder' and work['state'] == 'IMPLEMENTING':
                    self._fail(work, 'candidate_failed',
                               [x['id'] for x in self._current(work['blueprint'])['verification_obligations'] if x['required']],
                               {'head': self.repo.head, 'package': work['package']['digest']}, exc.reference)
            raise

    def _role_guard(self, before, name):
        current = self.work
        allowed = {before["state"]}
        if before["state"] == "PROVIDER_FEASIBLE":
            allowed.add("TESTER_FEASIBLE")
        if current["state"] not in allowed:
            raise Conflict("workflow stage changed during role execution")
        for key in ("request", "draft", "package", "candidate", "failures"):
            if before.get(key) != current.get(key):
                raise Conflict("role inputs changed during execution: " + key)

    def _prepare_role(
        self,
        name: str,
        generation: str,
        action_id: str,
        *,
        suite_ref: dict[str, Any] | None = None,
        receipt_id: str | None = None,
    ) -> dict[str, Any]:
        """Derive minimal current inputs. Callers cannot supply a custom hidden-data context."""
        with locked(self.lockfile):
            work = self.work
            if name == "planner" and work["state"] in {"INTAKE", "REPLAN_REQUIRED"}:
                context = {
                    "state": "INTAKE",
                    "request": self._current(work["request"]),
                    "previous_blueprint": (
                        self.store.get("PROJECT-BLUEPRINT")["payload"]
                        if self.store.exists("PROJECT-BLUEPRINT")
                        else None
                    ),
                    "prior_failure": self.store.resolve(work["failures"][-1])["payload"] if work["failures"] else None,
                    "expected_output": "planning_draft",
                    "instructions": "Propose a concrete Blueprint, Plan and consequence assessment. Preserve original identities; record any splits, merges or retirements with lineage. Scope, task paths and test paths are repository-relative: tests/** is valid; /tests/** is a container mount and invalid in a Plan. Correct rejected fields without silently weakening requirements or permissions.",
                }
                return lambda: self.roles.run(
                    name,
                    generation,
                    action_id,
                    context,
                    inputs=[work["request"]],
                    receipt_id=receipt_id,
                    accept_guard=lambda: self._role_guard(work, name),
                    approved_permissions=work["intake_permissions"],
                )
            inputs = [work["draft"]]
            context = {
                "state": work["state"],
                "request": self._current(work["request"]),
                "blueprint": self._current(work["blueprint"]),
                "plan": self._current(work["plan"]),
                "blueprint_ref": work["blueprint"],
                "plan_ref": work["plan"],
                "package_ref": work.get("package", work["draft"]),
            }
            include_independent = name in {
                "tester",
                "reviewer",
                "safety_reviewer",
                "debugger",
            }
            scope = None
            if name == "tester" and work["state"] == "PROVIDER_FEASIBLE":
                inputs += [work["provider_feasibility"]]
                if suite_ref is None:
                    context["expected_output"] = "test_design_draft"
                    context["instructions"] = (
                        "Author concrete cases from existing VER obligations. Use approximately 70% development and 30% independent cases where meaningful, with an engineering rationale. No undisclosed acceptance criteria."
                    )
                else:
                    inputs += [suite_ref]
                    context["test_design_ref"] = suite_ref
            elif name == "coder" and work["state"] == "PROVIDER_FEASIBLE":
                inputs += [work["provider_feasibility"]]
                context["handoff_ref"] = work["draft"]
                context["expected_output"] = "implementation_feasibility"
                context["instructions"] = (
                    "Assess implementation feasibility against the Plan concurrently with Tester test design. "
                    "This is preliminary: no production writes. A separate test handoff review is mandatory before coding."
                )
            elif name == "coder" and work["state"] == "TESTER_FEASIBLE":
                inputs += [work["tester_feasibility"]]
                context["handoff_ref"] = work["tester_feasibility"]
            elif name == "planner" and work["state"] == "FEASIBLE":
                inputs += [
                    work[x]
                    for x in (
                        "provider_feasibility",
                        "tester_feasibility",
                        "coder_feasibility",
                    )
                ]
            elif name == "coder" and work["state"] == "IMPLEMENTING":
                self._package_gate(work)
                inputs += [work["package"]]
                scope = context["plan"]["scope"]
                context["implementation_tasks"] = context["plan"]["tasks"]
                context["prior_implementation_trace"] = work.get("prior_implementation_trace", [])
                if work["failures"]:
                    failure = self.store.resolve(work['failures'][-1])['payload']
                    # Feasibility history is not an active implementation failure.
                    # Old records may predate the result/resume-state fields.
                    if failure.get('class') != 'feasibility_failure':
                        context['repair_failure'] = {k: failure[k] for k in ('class', 'owner', 'affected', 'material') if k in failure}
                        if failure.get('result'):
                            failed = self.store.resolve(failure['result'])['payload']
                            result = failed.get('result', {})
                            # Never send raw independent test logs/reviewer contents to Coder.
                            context['repair_result'] = {k: result[k] for k in ('status', 'failure_stage', 'obligation_ids', 'test_count') if k in result}
                            if failed.get('rejection_stage') == 'implementation_trace':
                                context['repair_result']['validation_findings'] = failed.get('findings', [])
                        context['repair_guidance'] = 'Fix production within the approved scope; do not modify tests or weaken obligations.'
                context["development_handoff"] = work["tester_feasibility"]

            elif name == "tester" and work["state"] == "CANDIDATE":
                results = self._matrix(work, False)
                inputs += [work["candidate"], *results]
                context["result_refs"] = results
                context["results"] = [self._current(x) for x in results]
            elif (
                name in {"reviewer", "safety_reviewer"} and work["state"] == "VERIFIED"
            ):
                inputs += [work[x] for x in ("candidate", "package", "tester_verdict")]
                candidate = self._candidate_gate(work)
                context["candidate_trace"] = candidate["trace"]
                context["implementation_trace"] = {
                    **candidate["trace"],
                    "changes": [c for c in candidate["trace"]["changes"]
                                if c["path"] not in development_hashes(self.store, work["suite"])],
                }
                context["test_provenance"] = {
                    "author": "tester", "materializer": "framework",
                    "suite_ref": work["suite"],
                    "development_hashes": development_hashes(self.store, work["suite"]),
                }
                context["review_output_contract"] = (
                    "findings lists unresolved defects only; approved requires findings=[]. "
                    "Put resolved issues and positive explanations in optional notes, never findings. Never suppress genuine defects. "
                    "candidate_trace includes controller-materialized Tester files; it is not Coder authorship."
                )
                context["tester_verdict"] = self._current(work["tester_verdict"])[
                    "output"
                ]
            elif name == "debugger" and work["state"] == "DIAGNOSING":
                inputs += [work["failures"][-1]]
                context["failure_ref"] = work["failures"][-1]
                context["failure"] = self._current(work["failures"][-1])
                context["failed_result"] = self._current(context["failure"]["result"])
                failed = context["failed_result"]
                evidence = failed.get("result", {}).get(
                    "evidence",
                    failed.get("evidence", [failed["log"]] if "log" in failed else []),
                )
                context["evidence"] = [
                    self.store.read_blob(h).decode("utf-8", errors="replace")
                    for h in evidence
                ]
            else:
                raise Conflict("role is not required at this workflow stage")
            expected_outputs = {
                ('tester', 'PROVIDER_FEASIBLE'): 'testability' if suite_ref else 'test_design_draft',
                ('coder', 'PROVIDER_FEASIBLE'): 'implementation_feasibility',
                ('coder', 'TESTER_FEASIBLE'): 'implementation_feasibility',
                ('planner', 'FEASIBLE'): 'planning',
                ('coder', 'IMPLEMENTING'): 'implementation_trace',
                ('tester', 'CANDIDATE'): 'verification',
                ('reviewer', 'VERIFIED'): 'review',
                ('safety_reviewer', 'VERIFIED'): 'safety_review',
                ('debugger', 'DIAGNOSING'): 'diagnosis',
            }
            context['expected_output'] = expected_outputs[(name, work['state'])]
            suite_ref = suite_ref or work.get("suite")
            def execute():
                with tempfile.TemporaryDirectory(
                    prefix="role-tests-", dir=self.store.root
                ) as tmp:
                    root = Path(tmp)
                    if suite_ref:
                        materialize(
                            self.store,
                            suite_ref,
                            root,
                            include_independent=include_independent,
                        )
                    return self.roles.run(
                        name,
                        generation,
                        action_id,
                        context,
                        inputs=inputs,
                        receipt_id=receipt_id,
                        accept_guard=lambda: self._role_guard(work, name),
                        approved_permissions=(
                            context["plan"]["permissions"]
                            if work["approvals"]
                            else work["intake_permissions"]
                        ),
                        scope=scope,
                        protected=(
                            development_hashes(self.store, suite_ref) if suite_ref else {}
                        ),
                        readonly_tests=root,
                        includes_independent=include_independent,
                        development_suite=suite_ref,
                    )

            return execute

    def import_planning(self, reference: dict[str, Any]) -> dict[str, Any]:
        work = self._need("INTAKE", "REPLAN_REQUIRED")
        value = self._role_output(reference, "planner", [work["request"]])
        if value["artifact_type"] != "planning_draft":
            raise FrameworkError("initial planning requires a semantic planning draft")
        try:
            return self.propose(value['blueprint'], value['plan'], value['consequences'], _expected_work=work)
        except Conflict:
            raise
        except FrameworkError as exc:
            with locked(self.lockfile), self.store.transaction():
                self._role_guard(work, 'planner')
                self._replan(self.work, reference, [str(exc)])
            raise RoleOutputRejected(str(exc), reference) from exc

    def import_test_design(self, reference: dict[str, Any]) -> dict[str, Any]:
        return self._preflight_import(reference, 'tester', lambda: self._import_test_design(reference))

    def _import_test_design(self, reference: dict[str, Any]) -> dict[str, Any]:
        from .test_artifacts import publish_case, suite

        with locked(self.lockfile), self.store.transaction():
            work = self._need("PROVIDER_FEASIBLE")
            if work.get("test_design_job") == reference:
                self._current(work["test_design_suite"])
                return work["test_design_suite"]
            value = self._role_output(
                reference, "tester", [work["draft"], work["provider_feasibility"]]
            )
            if value["artifact_type"] != "test_design_draft":
                raise FrameworkError("expected a Tester-authored concrete test design")
            declared = {x['id'] for x in self._current(work['blueprint'])['verification_obligations']}
            if any(not set(case['obligations']) <= declared for case in value['cases']):
                raise FrameworkError('test design references an obligation outside the current Blueprint')
            refs = []
            for index, case in enumerate(value["cases"]):
                key = self.work_id + "-CASE-" + digest(case["path"])[:12].upper()
                refs.append(
                    publish_case(
                        self.store,
                        key,
                        case["source"].encode(),
                        path=case["path"],
                        visibility=case["visibility"],
                        obligations=case["obligations"],
                        expected_revision=(
                            self.store.head(key)["revision"]
                            if self.store.exists(key)
                            else 0
                        ),
                    )
                )
            key = self.work_id + "-SUITE"
            obligations = [
                x["id"]
                for x in self._current(work["blueprint"])["verification_obligations"]
                if x["required"]
            ]
            suite_ref = suite(
                self.store,
                key,
                refs,
                obligations=obligations,
                rationale=value["allocation_rationale"],
                expected_revision=(
                    self.store.head(key)["revision"] if self.store.exists(key) else 0
                ),
            )
            work.update(test_design_job=reference, test_design_suite=suite_ref)
            self._save(work)
            return suite_ref

    def _fail(
        self,
        work: dict[str, Any],
        status: str,
        affected: list[str],
        material: dict[str, Any],
        result: dict[str, Any],
    ) -> dict[str, Any]:
        prior = [self.store.resolve(x)["payload"] for x in work["failures"]]
        failure = classify(status, affected, material, prior)
        failure["resume_state"] = work["state"]
        failure["result"] = result
        ref = self.store.publish(
            uid("FAILURE"),
            "failure",
            "framework",
            failure,
            [(result["id"], "derived_from")],
        )
        work["failures"].append(ref)
        work["state"] = (
            "DIAGNOSING"
            if failure["owner"] == "debugger"
            else "REPLAN_REQUIRED" if failure["owner"] == "planner" else "BLOCKED"
        )
        self._save(work)
        return ref

    def diagnose(self, role_ref: dict[str, Any]) -> None:
        with locked(self.lockfile), self.store.transaction():
            work = self._need("DIAGNOSING")
            failure = work["failures"][-1]
            output = self._role_output(role_ref, "debugger", [failure])
            if (
                output["artifact_type"] != "diagnosis"
                or output["failure_ref"] != failure
            ):
                raise FrameworkError("diagnosis does not cover the active failure")
            work.update(
                state="REPLAN_REQUIRED" if output["owner"] == "planner" else "BLOCKED",
                diagnosis=role_ref,
            )
            self._save(work)

    def resume(self, actor: str, *, repair_source: bool = False, automatic_budget: int | None = None) -> None:
        if not actor.strip():
            raise FrameworkError("human resume authorization is required")
        with locked(self.lockfile), self.store.transaction():
            work = self._need("BLOCKED")
            failure = self._current(work["failures"][-1])
            if automatic_budget is not None:
                if type(automatic_budget) is not int or not 0 <= automatic_budget <= 10:
                    raise FrameworkError("invalid automatic repair budget")
                if work.get("automatic_repairs", 0) >= automatic_budget:
                    raise Conflict("automatic repair budget exhausted")
                work["automatic_repairs"] = work.get("automatic_repairs", 0) + 1
            self._package_gate(work)
            work["state"] = "IMPLEMENTING" if repair_source else failure["resume_state"]
            if repair_source:
                if "candidate" in work:
                    self.store.invalidate([work["candidate"]["id"]])
                work.update(results=[], reviews={}, release_approvals=[])
            else:
                self._candidate_gate(work)
            self._save(work)
            self.store.event(
                "explicit_resume",
                {
                    "work": self.work_id,
                    "actor": actor,
                    "repair_source": repair_source,
                    "automatic_retry_budget": automatic_budget or 0,
                },
            )
