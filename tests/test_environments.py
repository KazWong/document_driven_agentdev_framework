import copy

import pytest

from agent_framework.common import Conflict, FrameworkError, LeaseRetained, digest
from agent_framework.policy import permissions, registry, risk_floor


def test_active_lease_blocks_retirement_and_gc_preserves_evidence(workflow):
    engine, backend, _ = workflow
    env = engine.environments
    with env.lease("ENV-001", "test"):
        with pytest.raises(Conflict):
            env.retire("ENV-001")
        assert env.gc(apply=True)["generations"] == []
    env.retire("ENV-001")
    assert env.gc()["generations"] == ["ENV-001"] and not backend.removed
    env.gc(apply=True)
    assert (
        backend.removed
        and env.get("ENV-001", require_available=False)["status"] == "evicted"
    )
    assert env.store.get("ENV-001")["payload"]["artifact_digest"] == backend.removed[0]


def test_cleanup_failure_keeps_lease_until_operator_recovery(workflow):
    e, _, _ = workflow
    env = e.environments
    with pytest.raises(LeaseRetained):
        with env.lease("ENV-001", "failed-job"):
            raise LeaseRetained("cleanup failed")
    lease = env.doctor()["leases"][0]
    with pytest.raises(Conflict):
        env.retire("ENV-001")
    env.recover_lease(
        lease["token"],
        actor="operator",
        verification_note="execution was inspected and stopped",
    )
    env.retire("ENV-001")


def test_resolver_rejects_unknown_capability_and_constraint(workflow):
    e, _, _ = workflow
    from conftest import blueprint

    req = blueprint()["environment_requirements"][0]
    req["capability"] = "unknown"
    with pytest.raises(FrameworkError):
        e.environments.resolve(req, "ENV-001")
    req["capability"] = "test"
    req["constraints"]["invented"] = True
    with pytest.raises(FrameworkError):
        e.environments.resolve(req, "ENV-001")


def test_unknown_permission_and_automatic_physical_actions_rejected():
    default = copy.deepcopy(registry()["default_execution_permissions"])
    with pytest.raises(FrameworkError):
        permissions({**default, "unrestricted": True})
    with pytest.raises(FrameworkError):
        permissions({**default, "physical_motion": True})
    assert risk_floor({**default, "device_write": True}, ["ordinary_software"]) == "R3"
    assert risk_floor(default, ["concurrency"]) == "R2"


def test_named_credentials_are_explicit_and_not_inherited(workflow, tmp_path):
    e, _, _ = workflow
    secret = tmp_path / "auth.json"
    secret.write_text('{"test_only":true}')
    secret.chmod(0o600)
    e.environments.register_credential("codex-auth", secret)
    assert e.environments.credentials([]) == {}
    assert e.environments.credentials(["codex-auth"]) == {
        "/credentials/codex-auth": secret
    }
    with pytest.raises(FrameworkError):
        e.environments.credentials(["unknown"])
    secret.chmod(0o644)
    with pytest.raises(FrameworkError):
        e.environments.credentials(["codex-auth"])


def test_provider_replacement_cannot_race_a_promotion_lease(workflow):
    e, _, _ = workflow
    env = e.environments
    replacement = copy.deepcopy(env.provider("test-provider"))
    replacement["provider_version"] = "9.0.0"
    with env.lease("ENV-001", "promotion"):
        with pytest.raises(Conflict, match="active execution/promotion lease"):
            with env.store.transaction():
                env._register_provider(replacement, {"test_only": True})
    with env.store.transaction():
        env._register_provider(replacement, {"test_only": True})
    assert env.provider("test-provider")["provider_version"] == "9.0.0"


def test_provider_update_cannot_introduce_a_bootstrap_cycle(workflow):
    e, _, _ = workflow
    env = e.environments
    second = copy.deepcopy(env.provider("test-provider"))
    second.update(provider_id="second-provider", bootstrap_requires=["test-provider"])
    env._register_provider(second, {"test_only": True})
    original = copy.deepcopy(env.provider("test-provider"))
    original.update(provider_version="2.0.0", bootstrap_requires=["second-provider"])
    with pytest.raises(FrameworkError, match="cycle"):
        env._register_provider(original, {"test_only": True})


def test_provider_feasibility_executes_resolver_and_routes_rejection(workflow):
    e, backend, _ = workflow
    original = backend.execute
    from agent_framework.common import write_json

    def reject(request):
        result = original(request)
        write_json(
            request.output / "resolution.json",
            {
                "schema_version": 1,
                "compatible": False,
                "capabilities": ["test"],
                "constraints": {"platform": "unit"},
                "findings": ["Unsupported requested behavior"],
            },
        )
        return result

    backend.execute = reject
    e.provider_preflight({"ENVREQ-001": "ENV-001"})
    assert e.work["state"] == "REPLAN_REQUIRED"
    assert backend.requests[-1].argv == ["resolve"]
    assert e.environments.store.list("provider_feasibility")
