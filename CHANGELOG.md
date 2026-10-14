## Unreleased - v2.1.0 repair 20261014-r1 (2026-10-14)

Repair bounded Planner and preflight rejection handling, typed stage bindings, replan diagnostics, Coder trace validation before writes, crash-safe file application and atomic scheduler receipts. Recover exact candidate intents before and after Git commit. Harden explicit remote authorization, Git pathspecs/SSH forwarding/multiple destinations, Bitbucket review freshness, Docker TLS/mount paths, private state and environment retirement. Add 54 framework regression cases and a separately pinned fresh-run test kit. Preserve original requirements, independent tests, approval gates and historical evidence. See `docs/repair-20261014.md`; live acceptance is pending.

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
