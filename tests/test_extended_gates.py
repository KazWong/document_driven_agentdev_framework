import copy

import pytest

from agent_framework.common import Conflict, FrameworkError, digest
from agent_framework.store import Store
from agent_framework.test_artifacts import publish_case
from conftest import (
    accepted,
    blueprint,
    changes,
    make_candidate,
    plan,
    preflight,
    targeted_review,
)


def test_r2_requires_safety_review_and_one_release_approver(workflow):
    e, _, suite = workflow
    p = plan()
    p["risk_class"] = "R2"
    e.propose(blueprint(), p, ["concurrency"])
    make_candidate(e, suite)
    targeted_review(e)
    assert e.work["state"] == "VERIFIED"
    with pytest.raises(Conflict):
        e.accepting()
    safety = e.run_role("safety_reviewer", "ENV-001", "role")
    e.review(safety)
    e.accepting()
    e.verify("ENVREQ-001", "verify", final=True)
    e.accept()
    value = e.work["acceptance"]["digest"]
    e.approve("person-one", value, release=True)
    assert e.work["state"] == "RELEASE_APPROVED"
    with pytest.raises(FrameworkError):
        e.approve("person-one", value, release=True)
    e.promote()


def test_two_environment_cells_cannot_substitute_for_one_another(workflow):
    e, _, suite = workflow
    bp = blueprint()
    bp["environment_requirements"].append(
        {**bp["environment_requirements"][0], "id": "ENVREQ-002"}
    )
    bp["final_acceptance"]["required_environments"].append("ENVREQ-002")
    e.propose(bp, plan(), ["ordinary_software"])
    e.provider_preflight({"ENVREQ-001": "ENV-001", "ENVREQ-002": "ENV-001"})
    tester = e.run_role("tester", "ENV-001", "role", suite_ref=suite)
    e.tester_preflight(suite, tester)
    coder = e.run_role("coder", "ENV-001", "role")
    e.coder_preflight(coder)
    planner = e.run_role("planner", "ENV-001", "role")
    e.reconcile(planner)
    e.approve("person", e.work["package"]["digest"])
    e.start()
    e.run_role("coder", "ENV-001", "role")
    e.candidate(changes())
    first = e.verify("ENVREQ-001", "verify")
    with pytest.raises(Conflict, match="ENVREQ-002"):
        e.run_role("tester", "ENV-001", "role")
    e.verify("ENVREQ-002", "verify")
    assert e.store.head(first["id"])["state"] == "CURRENT"
    tester = e.run_role("tester", "ENV-001", "role")
    e.verified(tester)
    reviewer = e.run_role("reviewer", "ENV-001", "role")
    e.review(reviewer)
    e.accepting()
    e.verify("ENVREQ-001", "verify", final=True)
    with pytest.raises(Conflict, match="ENVREQ-002"):
        e.accept()
    e.verify("ENVREQ-002", "verify", final=True)
    e.accept()


@pytest.mark.parametrize("malformed_report", [None, "null", "{broken", "[]"])
def test_new_provider_artifact_requires_its_own_acceptance_and_source_promotion(
    workflow,
    malformed_report,
):
    e, backend, suite = workflow
    provider = copy.deepcopy(e.environments.provider("test-provider"))
    provider.update(
        provider_id="unseen-synthetic-capability", capabilities=["unseen-capability"]
    )
    dynamic = {
        "project_source_sha",
        "artifact_digest",
        "environment_contract_ref",
        "acceptance_contract_ref",
    }
    p = plan()
    p["environment_release"] = {
        "provider_contract": {k: v for k, v in provider.items() if k not in dynamic},
        "environment_contract": {
            "backend": backend.name,
            "capabilities": ["unseen-capability"],
            "constraints": {"platform": "unit"},
            "base_generations": [],
        },
        "acceptance_action": {
            "argv": ["test"],
            "timeout_seconds": 30,
            "permissions": p["permissions"],
        },
    }
    e.propose(blueprint(), p, ["ordinary_software"])
    make_candidate(e, suite)
    provider.update(
        project_source_sha=e.repo.head,
        artifact_digest=digest(e.repo.files(e.repo.head)),
        environment_contract_ref=e.work["plan"],
        acceptance_contract_ref=suite,
    )
    generation = {
        "id": "ENV-NEW",
        "artifact_digest": "sha256:" + "b" * 64,
        "provider_id": provider["provider_id"],
        "provider_digest": digest(provider),
        **p["environment_release"]["environment_contract"],
    }
    if malformed_report is not None:
        original = backend.execute

        def malformed(request):
            result = original(request)
            (request.output / "result.json").write_text(malformed_report)
            return result

        backend.execute = malformed
    receipt = e.environments.accept_release_subject(e, provider, generation)
    if malformed_report is not None:
        assert e.store.resolve(receipt)["payload"]["status"] == "failed"
        assert e.work["state"] == "BLOCKED"
        assert e.store.resolve(receipt)["payload"]["report_error"]
        return
    assert e.store.resolve(receipt)["payload"]["status"] == "passed"
    with pytest.raises(Conflict):
        e.environments.register_release(e, provider, generation)
    targeted_review(e)
    e.accepting()
    e.verify("ENVREQ-001", "verify", final=True)
    e.accept()
    e.approve("person", e.work["acceptance"]["digest"], release=True)
    e.promote()
    e.environments.register_release(e, provider, generation)
    assert (
        e.environments.resolve(
            {
                "id": "ENVREQ-NEW",
                "capability": "unseen-capability",
                "provider_ref": provider["provider_id"],
                "constraints": {"platform": "unit"},
                "selection_authority": "user",
            },
            "ENV-NEW",
        )["id"]
        == "ENV-NEW"
    )


def test_coder_cannot_mutate_tester_owned_repository_tests(workflow):
    e, backend, suite = workflow
    preflight(e, suite)
    e.approve("person", e.work["package"]["digest"])
    e.start()
    original = backend.execute

    def tamper(request):
        result = original(request)
        if request.writable_project:
            (request.project / "tests/test_message.py").write_text("assert False")
        return result

    backend.execute = tamper
    with pytest.raises(FrameworkError, match="Tester-owned"):
        e.run_role("coder", "ENV-001", "role")
    assert e.repo.clean()


def test_development_tests_are_committed_with_tester_trace(workflow):
    e, _, suite = workflow
    make_candidate(e, suite)
    assert (e.repo.path / "tests/test_message.py").is_file()
    assert "tests/test_message.py" in {
        x["path"] for x in e._current(e.work["candidate"])["trace"]["changes"]
    }
    assert not (e.repo.path / "independent/test_secret.py").exists()


def test_retired_ids_are_not_reused_or_lost(tmp_path):
    with Store(tmp_path) as s:
        ref = s.publish("AA", "document", "planner", {})
        s.publish("BB", "document", "planner", {}, [("AA", "derived_from")])
        with pytest.raises(Conflict):
            s.retire("AA", reason="not actually obsolete")
        s.retire("BB", reason="obsolete leaf")
        s.retire("AA", reason="no live dependents")
        assert not s.list() and s.resolve(ref)["id"] == "AA"
        with pytest.raises(FrameworkError, match="reused"):
            s.publish("AA", "document", "planner", {}, expected_revision=1)
        assert s.check_integrity()["records"] == 2


def test_state_projection_tampering_is_detected(tmp_path):
    from agent_framework.common import IntegrityError

    with Store(tmp_path) as s:
        s.publish("AA", "document", "planner", {})
        s.invalidate(["AA"])
        s.db.execute("UPDATE heads SET state='CURRENT'")
        with pytest.raises(IntegrityError, match="projection"):
            s.check_integrity()
