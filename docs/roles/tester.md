# Tester policy

Generated from `src/agent_framework/data/policy.json`.

Product access: read_only.

Allowed outputs: test_design_draft, testability, test_design, verification.

Independent test access: owned_role_artifact_store.

Forbidden operations: production_write, new_acceptance_criterion, approve, scm_write.

The controller validates role, stage, input digest and exact candidate. Missing isolation blocks execution. This role grants no human approval and cannot mutate Git or controller state.
