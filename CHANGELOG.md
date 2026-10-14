## Unreleased — v2.1.0 automation repair (2026-10-13)

Concurrent Tester/Coder preflight; resumable run/watch driver; one human per approval gate for all risks; GitHub and Bitbucket Cloud branch/PR/CI/review integration; provenance, trace union, Codex transport and executable workspace fixes. Host-verified candidate; live environment and remote acceptance pending.

# 2.1.0 — clean architecture candidate

- Replace the legacy runtime with the `agent_framework` package and five operator entrypoints.
- Add canonical Blueprint/Plan contracts, revision-bound approval, complete candidate traceability and consequence-based gates.
- Implement an immutable ledger, typed dependency DAG, targeted invalidation, baselines, compressed history and static graph views.
- Isolate six role contracts, protect Tester-owned regression tests and retain independent cases outside Coder access.
- Add a neutral backend API, Docker execution, immutable managed generations, leases, explicit credentials and retained provenance during cleanup.
- Separate targeted verification from mandatory final acceptance and bind both to exact candidate/suite/environment identities.
- Add bounded failure routing, on-demand diagnosis, explicit recovery and copy-on-write historical-state migration.
- Retain thin main/generic environment definitions; remove permanent domain lanes and obsolete intelligent roles.
- Resolve architecture-principle naming to `P-*`; preserve decision IDs `D-001`–`D-043` and original requirement/design/verification identities.

Host verification accompanies the delivery. Built image artifacts, live agent acceptance and release promotion are not claimed.
