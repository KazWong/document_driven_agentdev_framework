# Coder policy

Generated from `src/agent_framework/data/policy.json`.

Product access: approved_paths_except_tester_owned.

Allowed outputs: implementation_feasibility, implementation_trace.

Independent test access: none.

Forbidden operations: tester_owned_write, approval_state_write, scm_write, authoritative_verdict.

The controller validates role, stage, input digest and exact candidate. Missing isolation blocks execution. This role grants no human approval and cannot mutate Git or controller state.
