# Reviewer policy

Generated from `src/agent_framework/data/policy.json`.

Product access: read_only.

Allowed outputs: review.

Independent test access: read_only_on_demand.

Forbidden operations: product_write, approve_human_gate, scm_write.

The controller validates role, stage, input digest and exact candidate. Missing isolation blocks execution. This role grants no human approval and cannot mutate Git or controller state.
