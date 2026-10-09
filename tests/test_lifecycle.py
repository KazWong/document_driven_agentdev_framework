import copy

import pytest

from agent_framework.common import Conflict, FrameworkError, digest
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


def test_complete_artifact_lifecycle_and_history(workflow):
    e, backend, suite = workflow
    accepted(e, suite)
    assert e.work["state"] == "ACCEPTED"
    e.approve("human-one", e.work["acceptance"]["digest"], release=True)
    e.promote()
    assert e.release_proof()["candidate_sha"] == e.repo.head
    e.close()
    assert e.work["state"] == "CLOSED"
    assert e.store.check_integrity()["records"] > 20
    assert all(
        not r.network and not r.read_only.get("/run/docker.sock")
        for r in backend.requests
    )


def test_no_approval_no_implementation(workflow):
    e, _, suite = workflow
    preflight(e, suite)
    with pytest.raises(Conflict):
        e.start()
    with pytest.raises(Conflict):
        e.approve("human", "0" * 64)
    assert e.work["state"] == "APPROVAL_READY"


def test_semantic_edit_invalidates_approval_without_erasing_it(workflow):
    e, _, suite = workflow
    preflight(e, suite)
    approval = e.approve("human", e.work["package"]["digest"])
    bp = blueprint()
    bp["requirements"][0]["text"] += " exactly"
    e.propose(bp, plan(), ["ordinary_software"])
    assert e.work["state"] == "DRAFT"
    assert e.store.head(approval["id"])["state"] == "STALE"
    assert e.store.resolve(approval)["payload"]["actor"] == "human"
    with pytest.raises(Conflict):
        e.start()


def test_actual_diff_must_have_complete_trace_before_commit(workflow):
    e, _, suite = workflow
    preflight(e, suite)
    e.approve("human", e.work["package"]["digest"])
    e.start()
    (e.repo.path / "app.txt").write_text("changed\n")
    before = e.repo.head
    with pytest.raises(FrameworkError):
        e.candidate(changes("missing.txt"))
    assert e.repo.head == before
    e.candidate(changes())
    assert e.repo.head != before


def test_scope_violation_cannot_commit(workflow):
    e, _, suite = workflow
    preflight(e, suite)
    e.approve("human", e.work["package"]["digest"])
    e.start()
    (e.repo.path / "unapproved.txt").write_text("outside scope\n")
    with pytest.raises(FrameworkError, match="outside approved scope"):
        e.candidate(changes("unapproved.txt"))


def test_final_acceptance_not_targeted_results(workflow):
    e, _, suite = workflow
    make_candidate(e, suite)
    targeted_review(e)
    e.accepting()
    with pytest.raises(Conflict, match="evidence"):
        e.accept()
    e.verify("ENVREQ-001", "verify", final=True)
    e.accept()


def test_dirty_checkout_blocks_acceptance_and_promotion(workflow):
    e, _, suite = workflow
    accepted(e, suite)
    e.approve("human", e.work["acceptance"]["digest"], release=True)
    (e.repo.path / "app.txt").write_text("unverified edits\n")
    with pytest.raises(Conflict, match="exact clean candidate"):
        e.promote()


def test_environment_retirement_blocks_promotion(workflow):
    e, _, suite = workflow
    accepted(e, suite)
    e.approve("human", e.work["acceptance"]["digest"], release=True)
    e.environments.retire("ENV-001")
    with pytest.raises(FrameworkError, match="not available"):
        e.promote()


def test_changed_suite_never_reuses_old_pass(workflow):
    e, _, suite = workflow
    accepted(e, suite)
    publish_case(
        e.store,
        "CASE-IND",
        b"# changed independent assertion\n",
        path="independent/test_secret.py",
        visibility="independent",
        obligations=["VER-001"],
        expected_revision=1,
    )
    with pytest.raises(Conflict):
        e.approve("human", e.work["acceptance"]["digest"], release=True)


@pytest.mark.parametrize(
    "status,owner",
    [
        ("candidate_failed", "coder"),
        ("environment_failure", "environment_project"),
        ("provider_failure", "provider_project"),
        ("bootstrap_failure", "bootstrap"),
        ("test_failure", "tester"),
    ],
)
def test_failures_are_routed_and_require_explicit_resume(workflow, status, owner):
    e, backend, suite = workflow
    make_candidate(e, suite)
    backend.status = status
    result = e.verify("ENVREQ-001", "verify")
    assert e.work["state"] == "BLOCKED"
    assert e.store.resolve(e.work["failures"][-1])["payload"]["owner"] == owner
    with pytest.raises(Conflict):
        e.verify("ENVREQ-001", "verify")
    e.resume("operator")
    e.verify("ENVREQ-001", "verify")
    assert e.work["state"] == "DIAGNOSING"
    diagnosis = e.run_role("debugger", "ENV-001", "role")
    e.diagnose(diagnosis)
    assert e.work["state"] == "BLOCKED"


def test_new_candidate_does_not_relabel_previous_evidence(workflow):
    e, backend, suite = workflow
    make_candidate(e, suite)
    backend.status = "candidate_failed"
    first = e.verify("ENVREQ-001", "verify")
    old_sha = e.repo.head
    e.resume("operator", repair_source=True)
    (e.repo.path / "app.txt").write_text("second candidate\n")
    e.candidate(changes())
    assert e.repo.head != old_sha and not e.work["results"]
    assert e.store.resolve(first)["payload"]["result"]["candidate_sha"] == old_sha
    assert e.store.head(first["id"])["state"] == "STALE"


@pytest.mark.parametrize(
    "mutation",
    [
        lambda r: r.update(candidate_sha="f" * 40),
        lambda r: r.update(test_count=0),
        lambda r: r.update(obligation_ids=["VER-UNDECLARED"]),
        lambda r: r.update(status="invented"),
    ],
)
def test_provider_report_cannot_forge_success(workflow, mutation):
    e, backend, suite = workflow
    make_candidate(e, suite)
    backend.mutate_output = mutation
    ref = e.verify("ENVREQ-001", "verify")
    assert e.store.resolve(ref)["payload"]["result"]["status"] == "provider_failure"
    assert e.work["state"] == "BLOCKED"


def test_advisory_backend_is_not_authoritative(workflow):
    e, backend, suite = workflow
    make_candidate(e, suite)
    backend.authoritative = False
    with pytest.raises(FrameworkError, match="advisory"):
        e.verify("ENVREQ-001", "verify")


def test_role_cannot_return_approval_or_wrong_identity(workflow):
    e, backend, suite = workflow
    e.provider_preflight({"ENVREQ-001": "ENV-001"})
    backend.mutate_output = lambda r: r.update(input_digest="0" * 64)
    with pytest.raises(FrameworkError, match="different input"):
        e.run_role("tester", "ENV-001", "role", suite_ref=suite)


def test_debugger_is_on_demand(workflow):
    e, _, _ = workflow
    with pytest.raises(Conflict):
        e.run_role("debugger", "ENV-001", "role")


def test_high_consequence_risk_cannot_be_downgraded(workflow):
    e, _, _ = workflow
    with pytest.raises(FrameworkError, match="minimum"):
        e.propose(blueprint(), plan(), ["safety_critical"])
