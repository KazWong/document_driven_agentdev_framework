import pytest

from agent_framework.common import Conflict, FrameworkError
from agent_framework.engine import Engine
from agent_framework.scm import Repository
from agent_framework.store import Store
from conftest import changes, make_candidate, preflight


def test_initial_planner_and_tester_author_concrete_artifacts(workflow, tmp_path):
    initial, _, _ = workflow
    with Store(tmp_path / "initial-state") as store:
        e = Engine(
            Repository(initial.repo.path), store, initial.environments, "WORK-INITIAL"
        )
        e.new("Specify a message tool")
        job = e.run_role("planner", "ENV-001", "role")
        e.import_planning(job)
        assert e.work["state"] == "DRAFT"
        e.provider_preflight({"ENVREQ-001": "ENV-001"})
        job = e.run_role("tester", "ENV-001", "role")
        suite = e.import_test_design(job)
        cases = store.resolve(suite)["payload"]["cases"]
        assert len(cases) == 2 and all(
            store.resolve(c)["owner"] == "tester" for c in cases
        )
        job = e.run_role("tester", "ENV-001", "role", suite_ref=suite)
        e.tester_preflight(suite, job)
        assert e.work["state"] == "TESTER_FEASIBLE"


def test_feasibility_failure_returns_to_planner(workflow):
    e, backend, suite = workflow
    e.provider_preflight({"ENVREQ-001": "ENV-001"})
    backend.mutate_output = lambda r: r["output"].update(
        feasible=False, findings=["REQ-001 lacks an observable acceptance condition"]
    )
    job = e.run_role("tester", "ENV-001", "role", suite_ref=suite)
    e.tester_preflight(suite, job)
    assert e.work["state"] == "REPLAN_REQUIRED"
    assert e._current(e.work["failures"][-1])["owner"] == "planner"


def test_worktree_isolation_preserves_original_checkout(workflow):
    e, _, suite = workflow
    original = e.repo.path
    original_head = e.repo.head
    make_candidate(e, suite)
    assert e.repo.path != original
    assert Repository(original).head == original_head
    assert (original / "app.txt").read_text() == "original\n"
    reopened = Engine(Repository(original), e.store, e.environments, e.work_id)
    assert reopened.repo.path == e.repo.path


def test_recover_commit_after_controller_transaction_failure(workflow, monkeypatch):
    e, _, suite = workflow
    preflight(e, suite)
    e.approve("person", e.work["package"]["digest"])
    e.start()
    e.run_role("coder", "ENV-001", "role")
    original = e._publish

    def interrupt(suffix, *args, **kwargs):
        if suffix == "CANDIDATE":
            raise RuntimeError("simulated crash after Git commit")
        return original(suffix, *args, **kwargs)

    monkeypatch.setattr(e, "_publish", interrupt)
    with pytest.raises(RuntimeError):
        e.candidate(changes())
    assert e.work["state"] == "IMPLEMENTING" and e.repo.clean()
    head = e.repo.head
    monkeypatch.setattr(e, "_publish", original)
    e.recover_candidate()
    assert (
        e.work["state"] == "CANDIDATE"
        and e._current(e.work["candidate"])["sha"] == head
    )
    assert not list(e.store.root.glob("candidate-intent-*.json"))


def test_backend_exception_is_recorded_without_a_candidate_failure(
    workflow, monkeypatch
):
    e, backend, suite = workflow
    make_candidate(e, suite)

    def fail(request):
        raise FrameworkError("image execution failed before candidate evaluation")

    monkeypatch.setattr(backend, "execute", fail)
    ref = e.verify("ENVREQ-001", "verify")
    result = e._current(ref)["result"]
    assert (
        result["status"] == "environment_failure"
        and result["candidate_evaluated"] is False
    )
    assert e.work["state"] == "BLOCKED"


def test_review_conflict_invokes_debugger(workflow):
    e, backend, suite = workflow
    make_candidate(e, suite)
    e.verify("ENVREQ-001", "verify")
    tester = e.run_role("tester", "ENV-001", "role")
    e.verified(tester)
    backend.mutate_output = lambda r: r["output"].update(
        verdict="changes_required",
        findings=["The successful tests conflict with observed behavior"],
    )
    reviewer = e.run_role("reviewer", "ENV-001", "role")
    e.review(reviewer)
    assert e.work["state"] == "DIAGNOSING"
    backend.mutate_output = None
    e.diagnose(e.run_role("debugger", "ENV-001", "role"))
    assert e.work["state"] == "BLOCKED"


def test_draft_permissions_cannot_expand_preapproval_role_authority(workflow):
    import copy
    from agent_framework.common import digest
    from conftest import blueprint, plan

    e, _, suite = workflow
    env = e.environments
    contract = copy.deepcopy(env.provider("test-provider"))
    contract["provider_version"] = "2.0.0"
    for action in contract["actions"]:
        if action["id"] == "role":
            action["permissions"]["credentials"] = ["undeclared-secret"]
    generation = {
        k: v
        for k, v in env.get("ENV-001").items()
        if k
        in {
            "id",
            "backend",
            "artifact_digest",
            "provider_id",
            "provider_digest",
            "capabilities",
            "constraints",
            "base_generations",
        }
    }
    generation.update(id="ENV-002", provider_digest=digest(contract))
    env._register_provider(contract, {"test_only": True})
    env._generation(generation, {"test_only": True})
    proposal = plan()
    proposal["permissions"]["credentials"] = ["undeclared-secret"]
    e.propose(blueprint(), proposal, ["ordinary_software"])
    e.provider_preflight({"ENVREQ-001": "ENV-002"})
    with pytest.raises(FrameworkError, match="credential access has not been approved"):
        e.run_role("tester", "ENV-002", "role", suite_ref=suite)
