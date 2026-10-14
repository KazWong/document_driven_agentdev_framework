"""Typed role jobs in backend isolation; prompts are not a security boundary."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
import stat
import tempfile
import uuid
from typing import Any

from .common import (
    Conflict,
    FrameworkError,
    RoleOutputRejected,
    atomic_write,
    bytes_digest,
    contained,
    digest,
    locked,
    read_json,
    write_json,
)
from .contracts import validate
from .environments import Environments
from .execution import ExecutionRequest, capture_execution
from .policy import in_scope, permissions, role as role_policy
from .scm import Repository
from .store import Store
from .test_artifacts import materialize


def inventory(root: Path) -> dict[str, tuple[str, int]]:
    result = {}
    for path in sorted(root.rglob("*")):
        mode = path.lstat().st_mode
        if stat.S_ISLNK(mode) or not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
            raise FrameworkError("role output contains a symlink or nonregular file")
        if path.is_file():
            result[path.relative_to(root).as_posix()] = (
                bytes_digest(path.read_bytes()),
                0o755 if mode & 0o111 else 0o644,
            )
    return result


class Roles:
    def __init__(self, store: Store, repo: Repository, environments: Environments):
        self.store, self.repo, self.environments = store, repo, environments

    def run(
        self,
        name: str,
        generation: str,
        action_id: str,
        context: dict[str, Any],
        *,
        inputs: list[dict[str, Any]],
        approved_permissions: dict[str, Any],
        scope: dict[str, list[str]] | None = None,
        protected: dict[str, str] | None = None,
        readonly_tests: Path | None = None,
        includes_independent: bool = False,
        development_suite: dict[str, Any] | None = None,
        accept_guard=None,
        receipt_id: str | None = None,
    ) -> dict[str, Any]:
        policy = role_policy(name)
        protected = protected or {}
        expected_head = self.repo.head
        for ref in inputs:
            self.store.resolve(ref, current=True)
        basis = {
            "role": name,
            "candidate_sha": expected_head,
            "inputs": inputs,
            "context": context,
        }
        input_digest = digest(basis)
        job_id = "JOB-" + uuid.uuid4().hex.upper()
        with (
            locked(self.store.root / ("agent-job-" + name + ".lock")),
            self.environments.lease(generation, job_id) as env,
        ):
            backend = self.environments.backend(env["backend"])
            if not backend.authoritative:
                raise FrameworkError(
                    "role execution requires an authoritative isolated backend"
                )
            provider = self.environments.provider(env["provider_id"])
            actions = [a for a in provider["actions"] if a["id"] == action_id]
            if len(actions) != 1:
                raise FrameworkError("role driver is absent from the approved provider")
            action = actions[0]
            permissions(action["permissions"], approved_permissions)
            writable = name == "coder" and scope is not None
            with tempfile.TemporaryDirectory(
                prefix="role-", dir=self.store.root
            ) as tmp:
                base = Path(tmp)
                project = base / "project"
                output = base / "output"
                ctx = base / "context"
                output.mkdir()
                ctx.mkdir()
                self.repo.snapshot(expected_head, project)
                if development_suite and writable:
                    materialize(
                        self.store,
                        development_suite,
                        project,
                        include_independent=False,
                    )
                before = inventory(project)
                write_json(
                    ctx / "input.json",
                    {
                        **basis,
                        "schema_version": 1,
                        "input_digest": input_digest,
                        "allowed_outputs": policy["role_outputs"],
                    },
                    0o644,
                )
                mounts = {
                    "/context": ctx,
                    **self.environments.credentials(
                        action["permissions"]["credentials"]
                    ),
                }
                if readonly_tests is not None:
                    if includes_independent and name not in {
                        "tester",
                        "reviewer",
                        "safety_reviewer",
                        "debugger",
                    }:
                        raise FrameworkError(
                            "this role has no access to independent tests"
                        )
                    mounts["/tests"] = readonly_tests
                # Existing development tests are protected even within a writable snapshot.
                existing = tuple(p for p in protected if p in before)
                request = ExecutionRequest(
                    env["artifact_digest"],
                    action["argv"],
                    project,
                    output,
                    action["timeout_seconds"],
                    action["permissions"]["network"] != "none",
                    read_only=mounts,
                    writable_project=writable,
                    protected_paths=existing,
                )
                execution = capture_execution(backend, request)
                log = self.store.blob(
                    (
                        execution.process.stdout + "\n" + execution.process.stderr
                    ).encode()
                )
                self.store.event(
                    "role_execution_completed",
                    {
                        "job": job_id,
                        "role": name,
                        "generation": generation,
                        "input_digest": input_digest,
                        "execution": execution.execution_id,
                        "log": log,
                        "process": {
                            k: v
                            for k, v in asdict(execution.process).items()
                            if k not in {"stdout", "stderr"}
                        },
                    },
                )
                if (
                    not execution.prepared
                    or execution.process.returncode
                    or execution.process.timed_out
                    or execution.process.output_limited
                    or execution.artifact_digest != env["artifact_digest"]
                    or execution.backend != backend.name
                ):
                    raise FrameworkError(
                        "isolated role execution failed; inspect the controller job log"
                    )
                raw_output = None
                def reject(exc, stage='role_output'):
                    ref = self.store.publish(
                        job_id, 'role_rejection', name,
                        {'input_digest': input_digest, 'candidate_sha': expected_head,
                         'inputs': inputs, 'generation': generation, 'execution_id': execution.execution_id,
                         'backend': backend.name, 'log': log, 'raw_output': raw_output,
                         'rejection_stage': stage, 'findings': [str(exc)]},
                        [(r['id'], 'derived_from') for r in inputs])
                    raise RoleOutputRejected(str(exc), ref) from exc

                try:
                    response_path = contained(output, "role-output.json")
                    if (
                        not response_path.is_file()
                        or response_path.stat().st_size > 4 * 1024 * 1024
                    ):
                        raise FrameworkError("missing or oversized role output")
                    raw_output = self.store.blob(response_path.read_bytes())
                    response = read_json(response_path)
                    if (
                        not isinstance(response, dict)
                        or set(response)
                        != {"schema_version", "role", "input_digest", "output"}
                        or response["schema_version"] != 1
                        or response["role"] != name
                        or response["input_digest"] != input_digest
                    ):
                        raise FrameworkError(
                            "role output is malformed or bound to a different input"
                        )
                    value = response["output"]
                    validate("RoleOutput", value)
                    if (
                        value["role"] != name
                        or value["artifact_type"] not in policy["role_outputs"]
                    ):
                        raise FrameworkError(
                            "role output attempts a different role's operation"
                        )
                    if "candidate_sha" in value and value["candidate_sha"] != expected_head:
                        raise FrameworkError("role reviewed a different candidate")
                except FrameworkError as exc:
                    reject(exc)
                try:
                    after = inventory(project)
                    changed = sorted(
                        k
                        for k in before.keys() | after.keys()
                        if before.get(k) != after.get(k)
                    )
                    if changed and not writable:
                        raise FrameworkError("read-only role modified candidate data")
                    for path in changed:
                        if not in_scope(path, scope) or path in protected:
                            raise FrameworkError(
                                "Coder output changes an unapproved or Tester-owned path: "
                                + path
                            )
                    if value['artifact_type'] != context['expected_output']:
                        raise FrameworkError('role output does not match the required workflow stage')
                    for key in ('package_ref', 'test_design_ref', 'handoff_ref', 'blueprint_ref', 'plan_ref', 'failure_ref'):
                        if key in value and value[key] != context.get(key):
                            raise FrameworkError('role output is bound to a different ' + key)
                    if value.get('feasible') is False and not value.get('findings'):
                        raise FrameworkError('infeasibility requires a concrete explanation')
                except FrameworkError as exc:
                    reject(exc, 'role_policy')
                if writable:
                    try:
                        from .scm import validate_changes
                        if (value['artifact_type'] != 'implementation_trace'
                                or value['package_ref'] != context['package_ref']
                                or value['incomplete_obligations']):
                            raise FrameworkError('Coder implementation trace is incomplete or bound to a different package')
                        validate_changes(value['changes'], changed, context['plan'])
                    except FrameworkError as exc:
                        reject(exc, 'implementation_trace')
                from . import worktree_apply
                journal = journal_value = None
                with locked(self.store.root / 'controller.lock'):
                    worktree_apply.recover(self.store, self.repo)
                    try:
                        with self.store.transaction():
                            if accept_guard is not None:
                                accept_guard()
                            if self.repo.head != expected_head or (writable and not self.repo.clean()):
                                raise Conflict('checkout changed during role execution; output remains unapplied')
                            for ref in inputs:
                                self.store.resolve(ref, current=True)
                            if changed:
                                journal, journal_value = worktree_apply.prepare(
                                    self.store, self.repo, job_id, changed, project, after)
                                worktree_apply.apply(self.store, self.repo, journal_value)
                            ref = self.store.publish(
                                job_id,
                                "role_output",
                                name,
                                {
                                    "output": value,
                                    "input_digest": input_digest,
                                    "candidate_sha": expected_head,
                                    "inputs": inputs,
                                    "generation": generation,
                                    "execution_id": execution.execution_id,
                                    "backend": backend.name,
                                    "log": log,
                                    "applied_paths": changed,
                                },
                                [(r["id"], "derived_from") for r in inputs],
                            )
                            if receipt_id:
                                self.store.publish(receipt_id, 'automation_receipt', 'framework',
                                                   {'job': ref}, [(ref['id'], 'derived_from')])
                    except BaseException:
                        if journal_value is not None:
                            # The SQLite transaction has rolled back; return the checkout
                            # to its known bytes. Keep the journal if recovery is uncertain.
                            worktree_apply.rollback(self.store, self.repo, journal_value)
                            journal.unlink(missing_ok=True)
                        raise
                    if journal:
                        journal.unlink(missing_ok=True)
                    return ref
