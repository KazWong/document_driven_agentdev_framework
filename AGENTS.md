# Repository agent contract

This repository uses the document-driven Agent-Gated Software Development Lifecycle.

1. Create/register work through `agentctl init-manifest` and `agentctl new`; import authoritative project inputs with `agentctl update` before planning.
2. Imported work-item documents are authoritative project inputs. The manifest controls project ownership, risk, scope, deterministic verification, isolation, rollback, promotion, and hardware policy.
3. Canonical work-item records live under the owning project's `.agent/work-items/<id>`. Linked Git worktrees under `.agent-state/worktrees` and verifier checkouts are disposable execution state.
4. Before Git-related work, read the project's `.agent/branching-policy.md`. One work item owns one feature branch. The framework, not the LLM, owns candidate commits, pushes, and pull-request publication.
5. Only the coder may write project source. Planning, verification analysis, debugging, safety review, code review, and PR preparation are read-only.
6. A code-changing work item must create a non-empty candidate commit. Local verification, required integration verification, AI review, and the remote PR head must bind to that exact candidate SHA.
7. Local verification runs from a detached mode-preserving candidate checkout. Integration verification runs from a disposable shared-workspace candidate checkout; generated build/test products must not contaminate the development worktree.
8. Required ROS work uses the external `ros2-humble` lane. A required test lane executing zero tests is a failure even when the process exits zero.
9. The framework may automatically push only the work-item feature branch and create the configured GitHub/Bitbucket PR after verification/review. Never force-push or write protected branches automatically. Merge remains human-gated.
10. Physical hardware exposure/execution remains separately human-authorized. Never weaken safety gates to unblock automation.
11. Preserve document revisions, plan revisions, runs, trace, approvals, and evidence. Invalidating a current binding must not erase historical evidence or Git commits.
12. Secrets stay in environment/provider credential storage and must never be committed, copied into evidence, or placed in process arguments.
