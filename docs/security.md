# Security model

## High-trust boundary

The Docker socket grants the main container effective control over the host daemon. A compromised repository, dependency, agent prompt, or tool can therefore affect the host. Restrict this environment to trusted users and code, keep Docker patched, and do not expose its daemon remotely without an authenticated transport.

## Controls

- Main and test processes run as the configured non-root UID/GID.
- Normal Codex writes are workspace-scoped and network access is disabled.
- Only the coder role is writable.
- Automated local commands are argument vectors from an approved manifest and pass an executable/path policy.
- Automated test lanes never include `compose.hardware.yaml`.
- `hardwarectl` requires R3, explicit manifest permission, two distinct approvals, a device path, actor, and literal confirmation.
- Bitbucket API writes require a recorded PR gate and `--execute`.
- Tokens are read from environment variables and are not placed in `.env` or command arguments.
- Workflow evidence is preserved and hashed.

## Residual risks

An allowlisted build system, compiler, Python test, or repository script can execute arbitrary repository code. The work-item approval therefore authorizes running trusted project tests; it is not a malware sandbox. Generic and firmware tests run in containers, but the main container still controls the host Docker daemon. Use isolated build hosts for untrusted pull requests.

Approval records are audit artifacts, not cryptographic signatures. Protect `.agent-state` with host permissions and backups. Enforce branch restrictions and required CI independently in Bitbucket.
