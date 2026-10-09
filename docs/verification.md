# Verification and release status

The source version is 2.1.0. Delivery remains a **release candidate** until the required live gates run on the exact packaged commit. The delivery report contains the actual test count, commit/tree IDs, commands, logs and artifact hashes. No test double is installed as a product backend.

| Evidence | What it establishes | Boundary |
|---|---|---|
| Host pytest suite | Lifecycle guards, record integrity, failure routing, recovery, isolation contracts, CLI and migration behavior | Role/provider execution uses explicit protocol test doubles |
| Real host subprocess tests | Input/output bounds, exit handling, environment filtering and descendant cleanup | Does not establish Docker isolation |
| Actual generic provider with host pytest | Distinguishes passing, failing, skipped and empty suites | Skipped or empty suites cannot establish a pass; Docker remains untested |
| Docker command contract tests | Immutable IDs, mount/privilege arguments, OOM/cleanup handling | Docker daemon not invoked |
| Clean wheel installation | Package resources and console entrypoints work outside the source checkout | Not image acceptance |
| Patch tree equality | Binary patch reconstructs the exact candidate tree including executable modes | Does not establish runtime safety |
| Graph benchmark | Independent BFS oracle, bounded SVG queries, archive lookup and full history integrity | Host-specific measurement, not a portable latency guarantee |
| Live Docker and Codex gates | Required before release promotion | Unrun in the delivery workspace |

`.agent/design/acceptance-cases.json` retains the 31 approved acceptance scenarios. Its implementation-test mappings are advisory coverage, not invented independent execution evidence. `.agent/design/implementation-map.json` links all 22 requirements to modules, tests and the approved task/decision identities. The original Blueprint text remains intact.

The graph benchmark runs approximately 1k, 10k and 100k live nodes and one million total revisions with 1,000 live heads. Reachability and invalidation are checked against an independent BFS. Compaction preserves every revision, and a full integrity scan validates the history after archival. Candidate source hashes bind the measurements. Regression budgets in `config/performance-budgets.json` were selected after an initial measured run, with headroom; they are engineering regression limits for a comparable host. They do not change acceptance requirements to turn an observed failure into a pass.

Reproduce the measurements in a new empty directory:

```bash
python scripts/benchmark_graph.py --directory /workspace/benchmark-run \
  --output /workspace/benchmark-results.json
python scripts/verify_release.py --benchmark /workspace/benchmark-results.json
```

The benchmark needs roughly a gigabyte for its history ledger plus graph databases. Metadata and journal entries remain after compression. SQLite reuses freed pages; optional `VACUUM` is measured separately. A graph is intentionally focused and bounded rather than rendering 100,000 nodes on one page.

`images/dependency-view.svg` is an actual bounded projection from the measured 1,000-node ledger: 12 nodes shown, 988 omitted. It illustrates stale propagation, not a fabricated lifecycle result.

Before promoting this framework itself, provision the approved Linux/amd64 Docker host, complete the immutable build lock, build/inspect both images, install an independently verified bootstrap seed, and execute the actual managed role workflow with retained independent tests. Exercise unknown-provider bootstrap, immutable candidate mounts, credentials, timeouts/cleanup/leases, environment repair/GC and the complete final matrix. Preserve the accepted previous controller for rollback. Remote SCM and physical hardware actions require their separately authorized procedures.
