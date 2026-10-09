# AI Agent Framework 2.1.0

A clean implementation of the approved v2.1 architecture: revision-bound engineering packages, isolated roles, immutable candidates, managed environments, traceable evidence and mandatory final acceptance.

**Delivery status: release candidate.** The accompanying verification report records host tests, graph measurements, wheel installation and patch reconstruction. Docker image builds, authenticated Codex roles and independent live acceptance have not run in the delivery workspace. The archive contains source and environment definitions, not prebuilt or accepted images.

The package name is `ai-agent-framework`; Python code lives in `agent_framework`. Architecture principles use `P-*`; the sole decision register uses `D-001` through `D-043`. Legacy runtime code is replaced. Existing product repositories are preserved, with an explicit historical-state importer.

## Install and inspect

Use Linux, Python 3.11 or newer and Git. The initial container target is Linux/amd64.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-runtime.txt
.venv/bin/python -m pip install --no-deps .
.venv/bin/agentctl --version
.venv/bin/agentctl doctor
```

For development checks:

```bash
.venv/bin/python -m pip install -r requirements-dev.txt
PYTHONPATH=src .venv/bin/python -m pytest -q
.venv/bin/python scripts/verify_release.py
.venv/bin/python scripts/generate_projection.py --check
```

`doctor` reports backend readiness; it does not establish release acceptance. Controller commands work without a Docker daemon, but role execution and required verification fail closed when the backend is unavailable.

## Start a project

```bash
agentctl --project /workspace/product init --id PROJECT-EXAMPLE
agentctl --project /workspace/product --state /workspace/state/example \
  --work WORK-001 new 'Implement the approved behavior'
agentctl --project /workspace/product --state /workspace/state/example \
  --work WORK-001 status
```

Keep state outside the product checkout and outside agent-visible mounts. `init` creates neutral project metadata and a Git repository. It does not choose a language, target or architecture. Existing clean Git repositories can be used directly without `init`.

Read [operations](docs/operations.md) for environment bootstrap, role stages, approvals, verification, failure recovery and migration. The [command reference](docs/commands.md) lists the actual CLI. Example semantic Blueprint and Plan files are in `examples/`; they are drafts, not approval records.

## Build the two environment definitions

Clone the supplied Git bundle when using the complete delivery, or work in the original candidate checkout. The build tool requires a clean committed source tree. Select immutable Ubuntu/Node image references and an exact Codex version in a copy of `config/build-lock.example.json`, stored outside the checkout.

```bash
python scripts/build_environments.py --lock /workspace/build-lock.json \
  --output /workspace/built-environments.json
```

The tool records actual Docker image IDs. This is a build inventory, not a promotion certificate. Base image references and client version are deliberately unresolved in the example; no build or successful agent run is implied. Operating-system packages come from the selected distribution repositories, so builds are identity-recorded rather than guaranteed byte-for-byte reproducible.

`compose.yaml` has exactly `main-development` and `generic-test`. The controller owns the Docker socket; role/provider containers do not receive it. Set the immutable image IDs and the host path/user/group variables named in the Compose file. Workspace and state paths must be identical inside and outside the controller for sibling-container bind mounts.

## Code and design

| Area | Source |
|---|---|
| Lifecycle, exact candidate gates, recovery | `src/agent_framework/engine.py` |
| Record ledger, revisions, integrity, archives | `store.py`, `common.py` |
| Dependency queries and static SVG/Mermaid | `graph.py` |
| Role contexts and Tester-owned artifacts | `roles.py`, `test_artifacts.py` |
| Environment generations, leases, acceptance, GC | `environments.py` |
| Generic execution and Docker implementation | `execution.py`, `docker_backend.py` |
| Trusted Git and optional GitHub delivery | `scm.py`, `remote.py` |
| Semantic schemas and policy authority | `src/agent_framework/data/` |
| Existing-state conversion | `migration.py` |

The [implemented architecture](docs/architecture.md), [verification boundaries](docs/verification.md), [approved design](docs/design/README.md) and `.agent/design/implementation-map.json` connect the code to all 22 requirements. Generated root schemas, policy and role documents are checked against their package-owned sources. Legacy Python imports and legacy intelligent roles are not compatibility APIs.
