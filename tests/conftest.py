from __future__ import annotations

import copy
import json
from pathlib import Path
import subprocess

import pytest

from agent_framework.common import digest, read_json, write_json
from agent_framework.engine import Engine
from agent_framework.environments import Environments
from agent_framework.execution import ExecutionResult, ProcessResult
from agent_framework.policy import registry
from agent_framework.scm import Repository
from agent_framework.store import Store
from agent_framework.test_artifacts import publish_case, suite


class IsolatedBackendDouble:
    """Contract test double, NEVER installed in the product backend registry."""

    name = "test-double"
    authoritative = True

    def __init__(self):
        self.status = "passed"
        self.count = 3
        self.requests = []
        self.mutate_output = None
        self.removed = []

    def inspect(self, artifact):
        return {"artifact_digest": artifact, "size_bytes": 42}

    def remove(self, artifact):
        self.removed.append(artifact)

    def execute(self, request):
        self.requests.append(request)
        assert not (request.project / ".git").exists()
        request.output.mkdir(exist_ok=True)
        data = read_json(request.read_only["/context"] / "input.json")
        if data.get("purpose") == "resolve":
            write_json(
                request.output / "resolution.json",
                {
                    "schema_version": 1,
                    "compatible": True,
                    "capabilities": data["capabilities"],
                    "constraints": data["constraints"],
                    "findings": [],
                },
            )
        elif request.argv == ["test"]:
            output = {
                "schema_version": 1,
                "status": self.status,
                "candidate_evaluated": self.status
                not in {
                    "environment_failure",
                    "bootstrap_failure",
                    "unsupported_requirement",
                },
                "test_count": self.count,
                "obligation_ids": data["obligations"],
                "failure_stage": "none" if self.status == "passed" else "execute",
            }
            if self.mutate_output:
                self.mutate_output(output)
            write_json(request.output / "result.json", output)
        else:
            name = data["role"]
            context = data["context"]
            state = context["state"]
            base = {"role": name}
            if name == "planner" and state == "INTAKE":
                output = {
                    **base,
                    "artifact_type": "planning_draft",
                    "blueprint": blueprint(),
                    "plan": plan(),
                    "consequences": ["ordinary_software"],
                }
            elif (
                name == "tester"
                and state == "PROVIDER_FEASIBLE"
                and "test_design_ref" not in context
            ):
                output = {
                    **base,
                    "artifact_type": "test_design_draft",
                    "allocation_rationale": "One development case and one independent boundary check for a small fixture",
                    "cases": [
                        {
                            "path": "tests/test_message.py",
                            "visibility": "development",
                            "obligations": ["VER-001"],
                            "source": "assert True\n",
                        },
                        {
                            "path": "independent/test_secret.py",
                            "visibility": "independent",
                            "obligations": ["VER-001"],
                            "source": "assert True\n",
                        },
                    ],
                }
            elif name == "tester" and state == "PROVIDER_FEASIBLE":
                output = {
                    **base,
                    "artifact_type": "testability",
                    "test_design_ref": context["test_design_ref"],
                    "feasible": True,
                    "findings": [],
                }
            elif name == "coder" and state == "TESTER_FEASIBLE":
                output = {
                    **base,
                    "artifact_type": "implementation_feasibility",
                    "package_ref": context["package_ref"],
                    "handoff_ref": context["handoff_ref"],
                    "feasible": True,
                    "findings": [],
                }
            elif name == "planner":
                output = {
                    **base,
                    "artifact_type": "planning",
                    "blueprint_ref": context["blueprint_ref"],
                    "plan_ref": context["plan_ref"],
                    "requirement_reconciliation": [
                        x["id"] for x in context["blueprint"]["requirements"]
                    ],
                    "findings": [],
                }
            elif name == "tester":
                output = {
                    **base,
                    "artifact_type": "verification",
                    "candidate_sha": data["candidate_sha"],
                    "result_refs": context["result_refs"],
                    "obligation_ids": ["VER-001"],
                    "verdict": "passed",
                }
            elif name in {"reviewer", "safety_reviewer"}:
                output = {
                    **base,
                    "artifact_type": (
                        "review" if name == "reviewer" else "safety_review"
                    ),
                    "candidate_sha": data["candidate_sha"],
                    "package_ref": context["package_ref"],
                    "verdict": "approved",
                    "findings": [],
                }
            elif name == "debugger":
                output = {
                    **base,
                    "artifact_type": "diagnosis",
                    "failure_ref": context["failure_ref"],
                    "owner": "coder",
                    "findings": ["TEST DOUBLE: investigate the failing implementation"],
                }
            elif name == "coder":
                (request.project / "app.txt").write_text("changed by isolated coder\n")
                assert "secret" not in json.dumps(data)
                assert not (
                    request.read_only["/tests"] / "independent/test_secret.py"
                ).exists()
                output = {
                    **base,
                    "artifact_type": "implementation_trace",
                    "candidate_sha": data["candidate_sha"],
                    "package_ref": context["package_ref"],
                    "changes": changes(),
                    "incomplete_obligations": [],
                }
            response = {
                "schema_version": 1,
                "role": name,
                "input_digest": data["input_digest"],
                "output": output,
            }
            if self.mutate_output:
                self.mutate_output(response)
            write_json(request.output / "role-output.json", response)
        return ExecutionResult(
            self.name,
            "test-double-execution",
            request.image,
            ProcessResult(0, "TEST DOUBLE; no live environment execution", ""),
            True,
        )


def changes(path="app.txt"):
    return [
        {
            "path": path,
            "requirement_ids": ["REQ-001"],
            "design_ids": ["CMP-001"],
            "task_ids": ["TASK-001"],
        }
    ]


def blueprint():
    return {
        "schema_version": 1,
        "artifact_type": "blueprint",
        "project_id": "PROJECT-TEST",
        "status": "draft",
        "requirements": [
            {
                "id": "REQ-001",
                "text": "The program emits the approved message",
                "disposition": "required",
            }
        ],
        "components": [{"id": "CMP-001", "text": "Message component"}],
        "interfaces": [],
        "verification_obligations": [
            {"id": "VER-001", "text": "Check the emitted message", "required": True}
        ],
        "traceability": [
            {
                "requirement": "REQ-001",
                "design_elements": ["CMP-001"],
                "verifications": ["VER-001"],
            }
        ],
        "environment_requirements": [
            {
                "id": "ENVREQ-001",
                "capability": "test",
                "provider_ref": "test-provider",
                "constraints": {"platform": "unit"},
                "selection_authority": "user",
            }
        ],
        "final_acceptance": {
            "obligations": ["VER-001"],
            "required_environments": ["ENVREQ-001"],
        },
        "lineage": [],
    }


def plan():
    return {
        "tasks": [
            {
                "id": "TASK-001",
                "title": "Change message",
                "requirements": ["REQ-001"],
                "design": ["CMP-001"],
                "paths": ["app.txt", "tests/**"],
            }
        ],
        "scope": {"include": ["app.txt", "tests/**"], "exclude": []},
        "risk_class": "R1",
        "permissions": copy.deepcopy(registry()["default_execution_permissions"]),
        "delivery": "artifact",
    }


@pytest.fixture
def workflow(tmp_path):
    product = tmp_path / "product"
    product.mkdir()
    (product / "app.txt").write_text("original\n")
    subprocess.run(
        ["git", "init", "--initial-branch=main", str(product)],
        check=True,
        capture_output=True,
    )
    subprocess.run(["git", "-C", str(product), "add", "."], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(product),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@localhost",
            "commit",
            "-m",
            "initial",
        ],
        check=True,
        capture_output=True,
    )
    backend = IsolatedBackendDouble()
    envs = Environments(tmp_path / "environments", {backend.name: backend})
    ref = {"id": "CONTRACT-001", "revision": 1, "digest": "f" * 64}
    provider = {
        "schema_version": 1,
        "provider_id": "test-provider",
        "provider_version": "1.0.0",
        "contract_version": 1,
        "project_source_sha": "1" * 40,
        "artifact_digest": "2" * 64,
        "capabilities": ["test"],
        "requirement_schema": {
            "type": "object",
            "properties": {"platform": {"const": "unit"}},
            "additionalProperties": False,
        },
        "resolver_action": "resolve",
        "bootstrap_requires": [],
        "environment_contract_ref": ref,
        "acceptance_contract_ref": ref,
        "actions": [
            {
                "id": x,
                "argv": ["test" if x == "verify" else x],
                "timeout_seconds": 30,
                "permissions": copy.deepcopy(
                    registry()["default_execution_permissions"]
                ),
                "result_schema_ref": ref,
            }
            for x in ("resolve", "verify", "role")
        ],
    }
    generation = {
        "id": "ENV-001",
        "backend": backend.name,
        "artifact_digest": "sha256:" + "3" * 64,
        "provider_id": provider["provider_id"],
        "provider_digest": digest(provider),
        "capabilities": ["test"],
        "constraints": {"platform": "unit"},
        "base_generations": [],
    }
    envs.bootstrap(
        provider,
        generation,
        actor="seed-tester",
        release_digest=digest({"provider": provider, "generation": generation}),
        verification_note="TEST FIXTURE; not a release attestation",
    )
    engine = Engine(Repository(product), Store(tmp_path / "state"), envs, "WORK-001")
    engine.new("Change message")
    engine.propose(blueprint(), plan(), ["ordinary_software"])
    dev = publish_case(
        engine.store,
        "CASE-DEV",
        b"assert True\n",
        path="tests/test_message.py",
        visibility="development",
        obligations=["VER-001"],
    )
    independent = publish_case(
        engine.store,
        "CASE-IND",
        b"# secret assertion\nassert True\n",
        path="independent/test_secret.py",
        visibility="independent",
        obligations=["VER-001"],
    )
    sref = suite(
        engine.store,
        "SUITE-001",
        [dev, independent],
        obligations=["VER-001"],
        rationale="Small fixture: one development and one independent boundary test; count is not a gate",
    )
    yield engine, backend, sref
    engine.store.close()
    envs.store.close()


def preflight(engine, sref):
    engine.provider_preflight({"ENVREQ-001": "ENV-001"})
    tester = engine.run_role("tester", "ENV-001", "role", suite_ref=sref)
    engine.tester_preflight(sref, tester)
    coder = engine.run_role("coder", "ENV-001", "role")
    engine.coder_preflight(coder)
    planner = engine.run_role("planner", "ENV-001", "role")
    engine.reconcile(planner)


def make_candidate(engine, sref):
    preflight(engine, sref)
    engine.approve("human-one", engine.work["package"]["digest"])
    engine.start()
    engine.run_role("coder", "ENV-001", "role")
    engine.candidate(changes())


def targeted_review(engine):
    engine.verify("ENVREQ-001", "verify")
    tester = engine.run_role("tester", "ENV-001", "role")
    engine.verified(tester)
    reviewer = engine.run_role("reviewer", "ENV-001", "role")
    engine.review(reviewer)


def accepted(engine, sref):
    make_candidate(engine, sref)
    targeted_review(engine)
    engine.accepting()
    engine.verify("ENVREQ-001", "verify", final=True)
    engine.accept()
