# Planner policy

Generated from `src/agent_framework/data/policy.json`.

Product access: read_only.

Allowed outputs: planning_draft, planning.

Independent test access: none.

Forbidden operations: production_write, test_implementation_write, approve, scm_write.

The controller validates role, stage, input digest and exact candidate. Missing isolation blocks execution. This role grants no human approval and cannot mutate Git or controller state.
