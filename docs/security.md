# Security model

## High-trust boundary

`main-development` mounts the host Docker socket and can therefore instruct the host Docker daemon. It is a high-trust development component. v2.0.2 also grants only `main-development` the outer-container capabilities/security profile required for Codex's nested Bubblewrap sandbox. The temporary auth helper and generic/firmware test services do not inherit that relaxation.

## Controls

- Development/test images run as the configured non-root user.
- Codex keeps its own read-only/workspace-write sandbox separation; the sandbox is not disabled.
- `/usr/local/bin/bwrap` is a compatibility wrapper over the real setuid `/usr/bin/bwrap` and removes only the fresh `--proc /proc` request that the outer container rejects.
- Work-item documents, plans, approvals, trace, and evidence are project-local operational records and ignored by Git.
- Framework candidate commits stage only approved source paths and reject empty candidates.
- Local/integration verification operate on exact detached candidate checkouts, not mutable development state.
- Required ROS test lanes fail closed on zero/missing executed-test evidence.
- Automatic SCM publication is limited to the work-item feature branch; no automatic force push or protected-branch write is permitted.
- GitHub tokens remain in provider credential/environment storage; `GH_TOKEN` is not placed in process argv or `.env`.
- Merge remains human-gated. Hardware/device exposure remains separately human-authorized and is not enabled by automatic test lanes.

## Residual risks

Docker socket possession remains equivalent to powerful host authority. `seccomp=unconfined`/`apparmor=unconfined` on the main container expands its attack surface and is accepted only to permit the nested Codex sandbox; it must not be copied to auth/test services. Provider credentials can publish feature branches/PRs and must be scoped accordingly. Live Docker/ROS/provider behavior must still be acceptance-tested on the target host because packaging QA cannot emulate the user's daemon, FUSE mount, external ROS bundle, or remote repository policy.
