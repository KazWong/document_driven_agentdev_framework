"""Immutable environment generations, local providers, promotion and lease-safe GC."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import re
import tempfile
import uuid
from typing import Any, Iterator

from jsonschema import Draft202012Validator

from .common import (
    Conflict,
    FrameworkError,
    LeaseRetained,
    canonical,
    contained,
    digest,
    identifier,
    locked,
    now,
    read_json,
    sha,
    write_json,
)
from .contracts import validate
from .execution import EnvironmentBackend, ExecutionRequest, capture_execution
from .policy import permissions
from .store import Store


class Environments:
    def __init__(self, root: Path, backends: dict[str, EnvironmentBackend]):
        self.store = Store(root)
        self.backends = backends
        self.store.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS generations(id TEXT PRIMARY KEY, family TEXT NOT NULL, status TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS leases(token TEXT PRIMARY KEY, generation TEXT NOT NULL, owner TEXT NOT NULL, started TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS leases_generation ON leases(generation);
        """
        )

    @property
    def lockfile(self) -> Path:
        return self.store.root / "environment.lock"

    def backend(self, name: str) -> EnvironmentBackend:
        if name not in self.backends:
            raise FrameworkError("backend is not installed: " + name)
        return self.backends[name]

    def register_credential(self, name: str, path: Path) -> None:
        if (
            not re.fullmatch(r"[a-z][a-z0-9_-]{1,63}", name)
            or not path.is_file()
            or path.is_symlink()
        ):
            raise FrameworkError(
                "credential registration requires a safe name and regular file"
            )
        if path.stat().st_mode & 0o077:
            raise FrameworkError(
                "credential file must not be accessible to group/other users"
            )
        with locked(self.lockfile):
            file = self.store.root / "credentials.json"
            value = read_json(file) if file.exists() else {}
            value[name] = str(path.resolve())
            write_json(file, value)
            self.store.event("named_credential_registered", {"name": name})

    def credentials(self, names: list[str]) -> dict[str, Path]:
        file = self.store.root / "credentials.json"
        values = read_json(file) if file.exists() else {}
        mounts = {}
        for name in names:
            if name not in values or not re.fullmatch(r"[a-z][a-z0-9_-]{1,63}", name):
                raise FrameworkError("named credential is not registered: " + name)
            path = Path(values[name])
            if not path.is_file() or path.is_symlink() or path.stat().st_mode & 0o077:
                raise FrameworkError(
                    "credential source is unavailable or permissions changed"
                )
            mounts["/credentials/" + name] = path
        return mounts

    def provider(self, provider_id: str) -> dict[str, Any]:
        key = "PROVIDER-" + digest(provider_id)[:24].upper()
        return self.store.resolve(self.store.ref(key), current=True)["payload"][
            "contract"
        ]

    def _register_provider(
        self, contract: dict[str, Any], provenance: dict[str, Any]
    ) -> dict[str, Any]:
        validate("Provider", contract)
        Draft202012Validator.check_schema(contract["requirement_schema"])

        def local_refs(value: Any) -> None:
            if isinstance(value, dict):
                for key, child in value.items():
                    if key in {"$ref", "$dynamicRef"} and not child.startswith("#"):
                        raise FrameworkError(
                            "provider requirement schemas must not fetch external references"
                        )
                    local_refs(child)
            elif isinstance(value, list):
                for child in value:
                    local_refs(child)

        local_refs(contract["requirement_schema"])
        actions = {a["id"]: a for a in contract["actions"]}
        if (
            len(actions) != len(contract["actions"])
            or contract["resolver_action"] not in actions
        ):
            raise FrameworkError(
                "provider actions must be unique and include its resolver"
            )
        for action in actions.values():
            permissions(action["permissions"])
        for dependency in contract["bootstrap_requires"]:
            if dependency == contract["provider_id"]:
                raise FrameworkError("provider bootstrap self-cycle")
            self.provider(dependency)
        from .graph import topological

        contracts = {
            self.store.get(row["id"])["payload"]["contract"][
                "provider_id"
            ]: self.store.get(row["id"])["payload"]["contract"]
            for row in self.store.list("provider")
        }
        contracts[contract["provider_id"]] = contract
        topological(
            contracts,
            [
                (dependency, key)
                for key, item in contracts.items()
                for dependency in item["bootstrap_requires"]
            ],
        )
        key = "PROVIDER-" + digest(contract["provider_id"])[:24].upper()
        if self.store.exists(key):
            previous = self.provider(contract["provider_id"])
            # Existing live generations retain their original version and can be inspected.
            if previous == contract:
                return self.store.ref(key)
            for row in self.store.db.execute("SELECT DISTINCT generation FROM leases"):
                leased = self.store.get(row[0])["payload"]
                if leased["provider_id"] == contract["provider_id"]:
                    raise Conflict("provider has an active execution/promotion lease")
            if previous["provider_version"] == contract["provider_version"]:
                raise FrameworkError(
                    "provider content changed without a version change"
                )
        return self.store.publish(
            key,
            "provider",
            "framework",
            {"contract": contract, "provenance": provenance},
            expected_revision=(
                self.store.head(key)["revision"] if self.store.exists(key) else 0
            ),
        )

    def bootstrap(
        self,
        contract: dict[str, Any],
        generation: dict[str, Any],
        *,
        actor: str,
        release_digest: str,
        verification_note: str,
    ) -> dict[str, Any]:
        """Explicit trust-root installation by the controller operator, never a role action.

        The checksum must come from an independently verified release. This is not
        an acceptance bypass for later provider/environment changes.
        """
        if (
            not actor.strip()
            or not verification_note.strip()
            or len(sha(release_digest)) != 64
        ):
            raise FrameworkError(
                "bootstrap requires a human identity, release checksum and independent verification note"
            )
        if digest({"provider": contract, "generation": generation}) != release_digest:
            raise FrameworkError("bootstrap release checksum mismatch")
        with locked(self.lockfile), self.store.transaction():
            if self.store.list("provider") or self.store.list("environment"):
                raise Conflict("bootstrap is allowed only in an empty registry")
            proof = {
                "kind": "independent_release_seed",
                "actor": actor,
                "release_digest": release_digest,
                "note": verification_note,
            }
            self._register_provider(contract, proof)
            ref = self._generation(generation, proof)
            self.store.event("bootstrap_trust_root_installed", proof)
            return ref

    def register_release(
        self, source: Any, contract: dict[str, Any], generation: dict[str, Any]
    ) -> dict[str, Any]:
        """source is a trusted Engine, not a provider-supplied JSON certificate."""
        proof = source.release_proof()
        if contract["project_source_sha"] != proof["candidate_sha"]:
            raise FrameworkError(
                "provider release does not match the promoted source candidate"
            )
        # The subject is declared before source-project final acceptance and bound by it.
        subject = {
            "provider_digest": digest(contract),
            "generation_digest": digest(generation),
        }
        if proof["subject"] != subject:
            raise FrameworkError(
                "environment/provider artifact is outside the accepted release subject"
            )
        work = source.work
        if "subject_acceptance" not in work:
            raise FrameworkError("no independent built-environment acceptance receipt")
        receipt = source._current(work["subject_acceptance"], "environment_acceptance")
        if (
            receipt["subject"] != subject
            or receipt["status"] != "passed"
            or receipt["candidate_sha"] != proof["candidate_sha"]
        ):
            raise FrameworkError(
                "built environment was not accepted on its promoted source"
            )
        with locked(self.lockfile), self.store.transaction():
            self._register_provider(contract, proof)
            return self._generation(generation, proof)

    def accept_release_subject(
        self, source: Any, contract: dict[str, Any], generation: dict[str, Any]
    ) -> dict[str, Any]:
        """Test a built immutable artifact before it can enter the shared registry.

        Its source project follows the normal ECP/review/FAS workflow. Only the
        explicit first trust seed bypasses that workflow to break bootstrapping.
        """
        validate("Provider", contract)
        from .test_artifacts import materialize

        with locked(source.lockfile):
            work = source._need("CANDIDATE")
            candidate = source._candidate_gate(work)
            if work["results"]:
                raise Conflict(
                    "bind the environment subject before candidate verification begins"
                )
            plan = source._current(work["plan"])
            release = plan.get("environment_release")
            if release is None:
                raise FrameworkError(
                    "the approved ECP has no environment release contract"
                )
            dynamic = {
                "project_source_sha",
                "artifact_digest",
                "environment_contract_ref",
                "acceptance_contract_ref",
            }
            if {k: v for k, v in contract.items() if k not in dynamic} != release[
                "provider_contract"
            ]:
                raise FrameworkError(
                    "provider contract differs from the approved release policy"
                )
            if contract["project_source_sha"] != candidate["sha"] or contract[
                "artifact_digest"
            ] != digest(source.repo.files(candidate["sha"])):
                raise FrameworkError(
                    "provider source identity does not match the exact candidate tree"
                )
            if (
                contract["environment_contract_ref"] != work["plan"]
                or contract["acceptance_contract_ref"] != work["suite"]
            ):
                raise FrameworkError(
                    "provider contracts must reference its approved Plan and Tester suite"
                )
            env_fields = {
                "id",
                "backend",
                "artifact_digest",
                "provider_id",
                "provider_digest",
                "capabilities",
                "constraints",
                "base_generations",
            }
            if (
                set(generation) != env_fields
                or {
                    k: v
                    for k, v in generation.items()
                    if k
                    not in {"id", "artifact_digest", "provider_id", "provider_digest"}
                }
                != release["environment_contract"]
            ):
                raise FrameworkError(
                    "built environment differs from the approved family contract"
                )
            identifier(generation["id"])
            if generation["provider_id"] != contract["provider_id"] or generation[
                "provider_digest"
            ] != digest(contract):
                raise FrameworkError("environment/provider identity mismatch")
            backend = self.backend(generation["backend"])
            if not backend.authoritative:
                raise FrameworkError(
                    "environment acceptance requires an isolated authoritative backend"
                )
            backend.inspect(generation["artifact_digest"])
            action = release["acceptance_action"]
            permissions(action["permissions"], plan["permissions"])
            for base in generation["base_generations"]:
                self.get(base)
            subject = {
                "provider_digest": digest(contract),
                "generation_digest": digest(generation),
            }
            with source.store.transaction():
                candidate_ref = source._publish(
                    "CANDIDATE",
                    "candidate",
                    "framework",
                    {**candidate, "subject": subject},
                    [(work["package"]["id"], "implements")],
                )
                work.update(candidate=candidate_ref, subject=subject)
                source._save(work)
            run_id = "ENVACCEPT-" + uuid.uuid4().hex.upper()
            with tempfile.TemporaryDirectory(
                prefix="environment-acceptance-", dir=source.store.root
            ) as tmp:
                root = Path(tmp)
                project = root / "project"
                output = root / "output"
                tests = root / "tests"
                context = root / "context"
                output.mkdir()
                tests.mkdir()
                context.mkdir()
                source.repo.snapshot(candidate["sha"], project)
                materialize(
                    source.store, work["suite"], tests, include_independent=True
                )
                obligations = source._current(work["suite"])["obligations"]
                write_json(
                    context / "input.json",
                    {
                        "schema_version": 1,
                        "run_id": run_id,
                        "candidate_sha": candidate["sha"],
                        "obligations": obligations,
                        "purpose": "environment_acceptance",
                        "subject": subject,
                    },
                    0o644,
                )
                execution = capture_execution(
                    backend,
                    ExecutionRequest(
                        generation["artifact_digest"],
                        action["argv"],
                        project,
                        output,
                        action["timeout_seconds"],
                        action["permissions"]["network"] != "none",
                        read_only={
                            "/tests": tests,
                            "/context": context,
                            **self.credentials(action["permissions"]["credentials"]),
                        },
                    ),
                )
                log = source.store.blob(
                    (
                        execution.process.stdout + "\n" + execution.process.stderr
                    ).encode()
                )
                report_error = None
                try:
                    report_path = contained(output, "result.json")
                    if (
                        not report_path.is_file()
                        or report_path.stat().st_size > 4 * 1024 * 1024
                    ):
                        raise FrameworkError("missing or oversized acceptance report")
                    report = read_json(report_path)
                    if not isinstance(report, dict):
                        raise FrameworkError("acceptance report must be an object")
                    if not isinstance(report.get("obligation_ids"), list) or any(
                        not isinstance(item, str) for item in report["obligation_ids"]
                    ):
                        raise FrameworkError(
                            "acceptance obligations must be string IDs"
                        )
                    validate(
                        "ProviderResult",
                        {
                            **report,
                            "run_id": run_id,
                            "candidate_sha": candidate["sha"],
                            "provider_digest": digest(contract),
                            "environment_generation": generation["id"],
                            "environment_artifact_digest": generation[
                                "artifact_digest"
                            ].removeprefix("sha256:"),
                            "suite_digest": work["suite"]["digest"],
                            "evidence": [log],
                        },
                    )
                    if set(report) != {
                        "schema_version",
                        "status",
                        "candidate_evaluated",
                        "test_count",
                        "obligation_ids",
                        "failure_stage",
                    }:
                        raise FrameworkError(
                            "provider cannot stamp controller execution identity"
                        )
                except (FrameworkError, OSError) as exc:
                    report = {}
                    report_error = str(exc)
                passed = (
                    execution.prepared
                    and execution.backend == backend.name
                    and execution.artifact_digest == generation["artifact_digest"]
                    and not execution.process.returncode
                    and not execution.process.timed_out
                    and not execution.process.output_limited
                    and report.get("status") == "passed"
                    and report.get("candidate_evaluated") is True
                    and type(report.get("test_count")) is int
                    and report["test_count"] > 0
                    and set(report.get("obligation_ids", [])) == set(obligations)
                )
                with source.store.transaction():
                    source._candidate_gate(work)
                    value = {
                        "candidate_sha": candidate["sha"],
                        "subject": subject,
                        "status": "passed" if passed else "failed",
                        "test_count": report.get("test_count", 0),
                        "evidence": [log],
                        "execution_id": execution.execution_id,
                        "backend": backend.name,
                        "artifact_digest": generation["artifact_digest"],
                        "report": report,
                        "report_error": report_error,
                    }
                    ref = source.store.publish(
                        run_id,
                        "environment_acceptance",
                        "framework",
                        value,
                        [
                            (work["candidate"]["id"], "verifies"),
                            (work["suite"]["id"], "derived_from"),
                        ],
                    )
                    work["subject_acceptance"] = ref
                    source._save(work)
                    if not passed:
                        source._fail(
                            work,
                            "environment_failure",
                            obligations,
                            {"candidate": candidate["sha"], "subject": subject},
                            ref,
                        )
                        source.store.event(
                            "environment_acceptance_failed",
                            {
                                "receipt": ref,
                                "owner": "environment_project",
                                "automatic_retry_budget": 0,
                            },
                        )
                    return ref

    def _generation(
        self, value: dict[str, Any], proof: dict[str, Any]
    ) -> dict[str, Any]:
        fields = {
            "id",
            "backend",
            "artifact_digest",
            "provider_id",
            "provider_digest",
            "capabilities",
            "constraints",
            "base_generations",
        }
        if (
            set(value) != fields
            or not isinstance(value["constraints"], dict)
            or not value["capabilities"]
        ):
            raise FrameworkError("invalid environment generation contract")
        identifier(value["id"])
        if self.store.exists(value["id"]):
            raise Conflict("environment generation identity is immutable")
        provider = self.provider(value["provider_id"])
        if digest(provider) != value["provider_digest"] or not set(
            value["capabilities"]
        ) <= set(provider["capabilities"]):
            raise FrameworkError(
                "environment capabilities do not match the promoted provider"
            )
        inspected = self.backend(value["backend"]).inspect(value["artifact_digest"])
        if inspected["artifact_digest"] != value["artifact_digest"]:
            raise FrameworkError("backend returned a different environment artifact")
        dependencies = []
        for base in value["base_generations"]:
            self.get(base)
            dependencies.append((base, "derived_from"))
        family = digest(
            {
                k: (
                    sorted(value[k])
                    if k in {"capabilities", "base_generations"}
                    else value[k]
                )
                for k in (
                    "backend",
                    "provider_id",
                    "capabilities",
                    "constraints",
                    "base_generations",
                )
            }
        )
        ref = self.store.publish(
            value["id"],
            "environment",
            "framework",
            {
                **value,
                "family": family,
                "provenance": proof,
                "size_bytes": inspected.get("size_bytes", 0),
            },
            dependencies,
        )
        self.store.db.execute(
            "INSERT INTO generations VALUES(?,?,'promoted')", (value["id"], family)
        )
        return ref

    def get(self, generation: str, *, require_available: bool = True) -> dict[str, Any]:
        row = self.store.db.execute(
            "SELECT status FROM generations WHERE id=?", (generation,)
        ).fetchone()
        if row is None or (require_available and row["status"] != "promoted"):
            raise FrameworkError(
                "environment generation is not available: " + generation
            )
        value = self.store.resolve(self.store.ref(generation), current=True)["payload"]
        if require_available:
            provider = self.provider(value["provider_id"])
            if digest(provider) != value["provider_digest"]:
                raise Conflict(
                    "environment requires a different provider version; rebind explicitly"
                )
            self.backend(value["backend"]).inspect(value["artifact_digest"])
            for base in value["base_generations"]:
                self.get(base)
        return {**value, "status": row["status"]}

    def resolve(self, requirement: dict[str, Any], generation: str) -> dict[str, Any]:
        validate("EnvironmentRequirement", requirement)
        value = self.get(generation)
        provider = self.provider(value["provider_id"])
        if (
            requirement["provider_ref"] != provider["provider_id"]
            or requirement["capability"] not in value["capabilities"]
        ):
            raise FrameworkError(
                "environment does not support the requested provider/capability"
            )
        errors = list(
            Draft202012Validator(provider["requirement_schema"]).iter_errors(
                requirement["constraints"]
            )
        )
        if errors:
            raise FrameworkError(
                "unsupported environment requirements: " + errors[0].message
            )
        if any(
            value["constraints"].get(k) != v
            for k, v in requirement["constraints"].items()
        ):
            raise FrameworkError(
                "environment generation is incompatible with approved constraints"
            )
        return value

    def preflight(
        self,
        requirement: dict[str, Any],
        generation: str,
        approved_permissions: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute the promoted provider's compatibility resolver in isolation."""
        selected = self.resolve(requirement, generation)
        run_id = "RESOLVE-" + uuid.uuid4().hex.upper()
        with self.lease(generation, run_id) as env:
            provider = self.provider(env["provider_id"])
            action = next(
                a for a in provider["actions"] if a["id"] == provider["resolver_action"]
            )
            permissions(action["permissions"], approved_permissions)
            backend = self.backend(env["backend"])
            if not backend.authoritative:
                raise FrameworkError(
                    "provider feasibility requires an isolated backend"
                )
            with tempfile.TemporaryDirectory(
                prefix="resolver-", dir=self.store.root
            ) as tmp:
                root = Path(tmp)
                project, output, context = (
                    root / n for n in ("project", "output", "context")
                )
                for path in (project, output, context):
                    path.mkdir()
                input_value = {
                    "schema_version": 1,
                    "purpose": "resolve",
                    "requirement": requirement,
                    "capabilities": selected["capabilities"],
                    "constraints": selected["constraints"],
                }
                write_json(context / "input.json", input_value, 0o644)
                execution = capture_execution(
                    backend,
                    ExecutionRequest(
                        env["artifact_digest"],
                        action["argv"],
                        project,
                        output,
                        action["timeout_seconds"],
                        action["permissions"]["network"] != "none",
                        read_only={
                            "/context": context,
                            **self.credentials(action["permissions"]["credentials"]),
                        },
                    ),
                )
                log = self.store.blob(
                    (
                        execution.process.stdout + "\n" + execution.process.stderr
                    ).encode()
                )
                report, error = {}, None
                try:
                    path = contained(output, "resolution.json")
                    if not path.is_file() or path.stat().st_size > 1024 * 1024:
                        raise FrameworkError(
                            "missing or oversized compatibility report"
                        )
                    report = read_json(path)
                    if not isinstance(report, dict) or set(report) != {
                        "schema_version",
                        "compatible",
                        "capabilities",
                        "constraints",
                        "findings",
                    }:
                        raise FrameworkError("invalid compatibility envelope")
                    if (
                        report["schema_version"] != 1
                        or type(report["compatible"]) is not bool
                        or not isinstance(report["capabilities"], list)
                        or not all(isinstance(x, str) for x in report["capabilities"])
                        or not isinstance(report["constraints"], dict)
                        or not isinstance(report["findings"], list)
                        or not all(isinstance(x, str) for x in report["findings"])
                    ):
                        raise FrameworkError("invalid compatibility report types")
                    if (
                        not set(report["capabilities"]) <= set(selected["capabilities"])
                        or report["constraints"] != selected["constraints"]
                    ):
                        raise FrameworkError(
                            "resolver attempted to redefine its promoted environment"
                        )
                except (FrameworkError, OSError) as exc:
                    report, error = {}, str(exc)
                feasible = bool(
                    execution.prepared
                    and execution.backend == backend.name
                    and execution.artifact_digest == env["artifact_digest"]
                    and execution.process.returncode == 0
                    and not execution.process.timed_out
                    and not execution.process.output_limited
                    and report.get("compatible") is True
                    and requirement["capability"] in report.get("capabilities", [])
                    and not report.get("findings")
                )
                value = {
                    "feasible": feasible,
                    "requirement": requirement,
                    "generation": generation,
                    "provider_digest": env["provider_digest"],
                    "artifact_digest": env["artifact_digest"],
                    "execution_id": execution.execution_id,
                    "backend": backend.name,
                    "input_digest": digest(input_value),
                    "report": report,
                    "error": error,
                    "evidence": [log],
                }
                ref = self.store.publish(
                    run_id,
                    "provider_feasibility",
                    "framework",
                    value,
                    [(generation, "executes_on")],
                )
                return {"receipt": ref, **value}

    @contextmanager
    def lease(self, generation: str, owner: str) -> Iterator[dict[str, Any]]:
        token = uuid.uuid4().hex
        with locked(self.lockfile), self.store.transaction():
            value = self.get(generation)
            self.store.db.execute(
                "INSERT INTO leases VALUES(?,?,?,?)", (token, generation, owner, now())
            )
            self.store.event(
                "lease_acquired",
                {"token": token, "generation": generation, "owner": owner},
            )
        retained = False
        try:
            yield {**value, "lease_token": token}
        except LeaseRetained:
            retained = True
            self.store.event(
                "lease_retained_for_recovery",
                {"token": token, "generation": generation},
            )
            raise
        finally:
            if not retained:
                with locked(self.lockfile), self.store.transaction():
                    self.store.db.execute("DELETE FROM leases WHERE token=?", (token,))
                    self.store.event("lease_released", {"token": token})

    def recover_lease(self, token: str, *, actor: str, verification_note: str) -> None:
        if not actor.strip() or not verification_note.strip():
            raise FrameworkError(
                "lease recovery requires an operator and confirmation that the execution has stopped"
            )
        with locked(self.lockfile), self.store.transaction():
            if not self.store.db.execute(
                "SELECT 1 FROM leases WHERE token=?", (token,)
            ).fetchone():
                raise FrameworkError("unknown execution lease")
            self.store.db.execute("DELETE FROM leases WHERE token=?", (token,))
            self.store.event(
                "lease_recovered_by_operator",
                {
                    "token": token,
                    "actor": actor,
                    "verification_note": verification_note,
                },
            )

    def retire(self, generation: str) -> None:
        with locked(self.lockfile), self.store.transaction():
            self.get(generation)
            if self.store.db.execute(
                "SELECT 1 FROM leases WHERE generation=?", (generation,)
            ).fetchone():
                raise Conflict("environment has an active execution/promotion lease")
            self.store.db.execute(
                "UPDATE generations SET status='retired' WHERE id=?", (generation,)
            )
            self.store.event("environment_retired", {"generation": generation})

    def gc(self, *, apply: bool = False) -> dict[str, Any]:
        """Evict backend images only. Ledgers, providers, source and evidence persist."""
        with locked(self.lockfile), self.store.transaction():
            active = [
                self.get(r[0], require_available=False)
                for r in self.store.db.execute(
                    "SELECT id FROM generations WHERE status='promoted'"
                )
            ]
            keep = {x["artifact_digest"] for x in active}
            keep_ids = {b for x in active for b in x["base_generations"]}
            candidates = []
            for row in self.store.db.execute(
                "SELECT id FROM generations WHERE status='retired'"
            ).fetchall():
                value = self.get(row[0], require_available=False)
                if (
                    row[0] in keep_ids
                    or value["artifact_digest"] in keep
                    or self.store.db.execute(
                        "SELECT 1 FROM leases WHERE generation=?", (row[0],)
                    ).fetchone()
                ):
                    continue
                candidates.append(value)
            if apply:
                removed = set()
                for value in candidates:
                    key = (value["backend"], value["artifact_digest"])
                    if key not in removed:
                        self.backend(value["backend"]).remove(value["artifact_digest"])
                        removed.add(key)
                    self.store.db.execute(
                        "UPDATE generations SET status='evicted' WHERE id=?",
                        (value["id"],),
                    )
                    self.store.event(
                        "environment_image_evicted",
                        {
                            "generation": value["id"],
                            "artifact": value["artifact_digest"],
                        },
                    )
            return {
                "dry_run": not apply,
                "generations": [x["id"] for x in candidates],
                "estimated_reclaimable_bytes": sum(
                    x["size_bytes"]
                    for x in {
                        (v["backend"], v["artifact_digest"]): v for v in candidates
                    }.values()
                ),
            }

    def doctor(self) -> dict[str, Any]:
        return {
            "generations": [
                dict(x)
                for x in self.store.db.execute("SELECT * FROM generations ORDER BY id")
            ],
            "leases": [
                dict(x)
                for x in self.store.db.execute("SELECT * FROM leases ORDER BY started")
            ],
            "note": "Leases never expire automatically. A crashed controller requires explicit recovery after confirming no execution remains.",
        }
