"""Readable operator commands; --json is an explicit machine-readable projection."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any

from . import __version__
from .common import FrameworkError, atomic_write, read_json, write_json
from .docker_backend import DockerBackend
from .engine import Engine
from .environments import Environments
from .graph import explain, graph_data, mermaid, svg
from . import migration
from .policy import registry
from .scm import Repository
from .store import Store
from .test_artifacts import materialize, publish_case, suite


def readable(value: Any, indent: int = 0) -> str:
    if value is None:
        return "Done."
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        lines = []
        for key, item in value.items():
            title = key.replace("_", " ").capitalize()
            if isinstance(item, (dict, list)):
                lines.append(" " * indent + title + ":")
                lines.append(readable(item, indent + 2))
            else:
                lines.append(" " * indent + title + ": " + str(item))
        return "\n".join(lines)
    if isinstance(value, list):
        if not value:
            return " " * indent + "(none)"
        return "\n".join(
            " " * indent + "- " + readable(x, indent + 2).lstrip() for x in value
        )
    return str(value)


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="agentctl",
        description="AI Agent Framework 2.1: approved changes, isolated execution, exact-candidate evidence",
    )
    p.add_argument("--version", action="version", version=__version__)
    p.add_argument("--project", type=Path, default=Path.cwd())
    p.add_argument(
        "--state",
        type=Path,
        help="private controller directory outside the product checkout",
    )
    p.add_argument(
        "--environments", type=Path, help="shared environment registry directory"
    )
    p.add_argument("--work", default="WORK-001")
    p.add_argument("--docker-runtime-profile", type=Path, help="operator-owned sandbox compatibility proof/config")
    p.add_argument(
        "--json", action="store_true", help="emit the canonical machine projection"
    )
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="check backend readiness without claiming acceptance")
    q = sub.add_parser(
        "init", help="create a neutral repository; no technology scaffolding"
    )
    q.add_argument("--id", required=True)
    q = sub.add_parser("new")
    q.add_argument("request")
    q.add_argument("--permission-file", type=Path)
    sub.add_parser("status")
    q = sub.add_parser("propose")
    q.add_argument("blueprint", type=Path)
    q.add_argument("plan", type=Path)
    q.add_argument("--consequence", action="append", required=True)
    q = sub.add_parser("provider-preflight")
    q.add_argument("selections", type=Path)
    q = sub.add_parser("tester-preflight")
    q.add_argument("suite")
    q.add_argument("job")
    for name in (
        "coder-preflight",
        "reconcile",
        "verified",
        "review",
        "diagnose",
        "import-planning",
        "import-test-design",
    ):
        q = sub.add_parser(name)
        q.add_argument("job")
    q = sub.add_parser("role")
    q.add_argument("role", choices=list(registry()["roles"]))
    q.add_argument("--generation", required=True)
    q.add_argument("--action", required=True)
    q.add_argument("--suite")
    q = sub.add_parser("run", help="resume automatic lifecycle until human review or a diagnosed blocker")
    q.add_argument("--config", type=Path, required=True)
    q.add_argument("--watch", action="store_true")
    q.add_argument("--timeout", type=int, default=3600)
    q.add_argument("--poll-seconds", type=int, default=15)
    sub.add_parser("sync-review", help="import the current GitHub/Bitbucket human approval")
    q = sub.add_parser("approve")
    q.add_argument("--actor", required=True)
    q.add_argument("--digest", required=True)
    q.add_argument("--release", action="store_true")
    for name in (
        "start",
        "accepting",
        "accept",
        "close",
        "integrity",
        "ci",
        "recover-candidate",
        "recover-role",
    ):
        sub.add_parser(name)
    q = sub.add_parser("promote")
    q.add_argument("--authorize-remote", action="store_true")
    q = sub.add_parser("publish-pr")
    q.add_argument("--actor", required=True)
    q.add_argument("--title", required=True)
    q.add_argument("--body-file", type=Path, required=True)
    q = sub.add_parser("candidate")
    q.add_argument("trace", type=Path)
    q.add_argument("--subject", type=Path)
    q = sub.add_parser("verify")
    q.add_argument("environment")
    q.add_argument("--action", required=True)
    q.add_argument("--final", action="store_true")
    q = sub.add_parser("resume")
    q.add_argument("--actor", required=True)
    q.add_argument("--repair-source", action="store_true")
    q = sub.add_parser(
        "read", help="inspect any public or independent artifact as the operator"
    )
    q.add_argument("artifact")
    q.add_argument("--revision", type=int)
    q.add_argument("--content", action="store_true")
    q = sub.add_parser("evidence")
    q.add_argument("digest")
    q = sub.add_parser("graph")
    q.add_argument("--focus")
    q.add_argument("--view", default="overview")
    q.add_argument("--limit", type=int, default=100)
    q.add_argument("--baseline")
    q.add_argument(
        "--format", choices=["text", "json", "mermaid", "svg"], default="text"
    )
    q.add_argument("--output", type=Path)
    q = sub.add_parser("explain")
    q.add_argument("artifact")
    q = sub.add_parser("baseline")
    q.add_argument("id")
    q.add_argument("label")
    q.add_argument("--compact", action="store_true")
    sub.add_parser("compact")
    q = sub.add_parser("retire")
    q.add_argument("artifact")
    q.add_argument("--reason", required=True)
    q = sub.add_parser("test-add")
    q.add_argument("id")
    q.add_argument("source", type=Path)
    q.add_argument("--path", required=True)
    q.add_argument(
        "--visibility", choices=["development", "independent"], required=True
    )
    q.add_argument("--obligation", action="append", required=True)
    q.add_argument("--revision", type=int, default=0)
    q = sub.add_parser("suite")
    q.add_argument("id")
    q.add_argument("cases", nargs="+")
    q.add_argument("--obligation", action="append", required=True)
    q.add_argument("--rationale", required=True)
    q.add_argument("--revision", type=int, default=0)
    q = sub.add_parser("test-export")
    q.add_argument("suite")
    q.add_argument("directory", type=Path)
    q.add_argument("--include-independent", action="store_true")
    q = sub.add_parser("env-seed")
    q.add_argument("release", type=Path)
    q.add_argument("--actor", required=True)
    q.add_argument("--digest", required=True)
    q.add_argument("--verification-note", required=True)
    sub.add_parser("env-list")
    q = sub.add_parser("credential-register")
    q.add_argument("name")
    q.add_argument("file", type=Path)
    q = sub.add_parser("env-build")
    q.add_argument("source", type=Path)
    q.add_argument("--recipe", type=Path, required=True)
    q.add_argument("--network", action="store_true")
    q = sub.add_parser("env-retire")
    q.add_argument("generation")
    q = sub.add_parser("env-gc")
    q.add_argument("--apply", action="store_true")
    q = sub.add_parser("env-recover-lease")
    q.add_argument("token")
    q.add_argument("--actor", required=True)
    q.add_argument("--verification-note", required=True)
    q = sub.add_parser("env-publish")
    q.add_argument("release", type=Path)
    q = sub.add_parser("env-accept")
    q.add_argument("release", type=Path)
    q = sub.add_parser("migrate")
    q.add_argument("legacy", type=Path)
    q.add_argument("target", type=Path)
    q.add_argument("--apply", action="store_true")
    q.add_argument("--digest")
    q = sub.add_parser("rollback")
    q.add_argument("target", type=Path)
    q.add_argument("--actor", required=True)
    sub.add_parser(
        "hardware", help="show the separately approved physical-operation boundary"
    )
    return p


def execute(a: argparse.Namespace) -> Any:
    backend = DockerBackend(runtime_profile=a.docker_runtime_profile)
    if a.command == "doctor":
        return {
            "framework": __version__,
            "backend": backend.doctor(),
            "release_acceptance": "not established by doctor",
        }
    if a.command == "hardware":
        raise FrameworkError(
            "automatic physical execution is disabled; R3 operations require a separate reviewed procedure, one human approval per gate and an explicitly approved hardware provider"
        )
    if a.command == "migrate":
        if a.apply and not a.digest:
            raise FrameworkError(
                "review the dry-run input digest before applying migration"
            )
        return (
            migration.apply(a.legacy, a.target, expected_digest=a.digest)
            if a.apply
            else migration.plan(a.legacy, a.target)
        )
    if a.command == "rollback":
        return migration.rollback(a.target, actor=a.actor)
    if a.command == "init":
        from .common import identifier

        identifier(a.id)
        a.project.mkdir(parents=True, exist_ok=True)
        if any(a.project.iterdir()):
            raise FrameworkError("neutral project creation requires an empty directory")
        from .execution import ProcessExecutor

        runner = ProcessExecutor()
        result = runner.run(["git", "init", "--initial-branch=main", str(a.project)])
        if result.returncode:
            raise FrameworkError(result.stderr)
        write_json(
            a.project / "project.json",
            {"schema_version": 1, "project_id": a.id, "framework_version": __version__},
            0o644,
        )
        # Initial metadata is the only bootstrap commit; all source changes use candidates.
        result = runner.run(
            [
                "git",
                "-c",
                "core.hooksPath=/dev/null",
                "-c",
                "user.name=Framework Controller",
                "-c",
                "user.email=controller@localhost",
                "-c",
                "commit.gpgsign=false",
                "-C",
                str(a.project),
                "add",
                "project.json",
            ]
        )
        if result.returncode:
            raise FrameworkError(result.stderr)
        result = runner.run(
            [
                "git",
                "-c",
                "core.hooksPath=/dev/null",
                "-c",
                "user.name=Framework Controller",
                "-c",
                "user.email=controller@localhost",
                "-c",
                "commit.gpgsign=false",
                "-C",
                str(a.project),
                "commit",
                "-m",
                "Initialize neutral project",
            ]
        )
        if result.returncode:
            raise FrameworkError(result.stderr)
        return {
            "project": str(a.project.resolve()),
            "id": a.id,
            "next": "new <request>; then propose a Blueprint and Plan",
        }
    if a.state is None:
        raise FrameworkError(
            "--state must name a private controller directory outside the project"
        )
    envroot = a.environments or a.state.parent / "environments"
    for root in (a.state, envroot):
        if root.resolve().is_relative_to(a.project.resolve()):
            raise FrameworkError('controller and environment state must be outside the product checkout')
    if envroot.resolve() == a.state.resolve():
        raise FrameworkError('controller and environment ledgers must use distinct directories')
    environments = Environments(envroot, {"docker": backend})
    try:
        store = Store(a.state)
    except BaseException:
        environments.store.close()
        raise
    try:
        if a.command == "env-seed":
            release = read_json(a.release)
            return environments.bootstrap(
                release["provider"],
                release["generation"],
                actor=a.actor,
                release_digest=a.digest,
                verification_note=a.verification_note,
            )
        if a.command == "env-list":
            return environments.doctor()
        if a.command == "credential-register":
            return environments.register_credential(a.name, a.file)
        if a.command == "env-build":
            return {
                "artifact_digest": backend.build(
                    a.source, recipe=read_json(a.recipe), network=a.network
                ),
                "status": "built; requires managed-project acceptance before registration",
            }
        if a.command == "env-retire":
            return environments.retire(a.generation)
        if a.command == "env-gc":
            return environments.gc(apply=a.apply)
        if a.command == "env-recover-lease":
            return environments.recover_lease(
                a.token, actor=a.actor, verification_note=a.verification_note
            )
        if a.command == "integrity":
            return store.check_integrity()
        if a.command == "read":
            record = store.get(a.artifact, a.revision)
            return (
                store.read_blob(record["payload"]["content"]).decode(
                    "utf-8", errors="replace"
                )
                if a.content
                else record
            )
        if a.command == "evidence":
            return store.read_blob(a.digest).decode("utf-8", errors="replace")
        if a.command == "baseline":
            return store.baseline(a.id, a.label, compact=a.compact)
        if a.command == "compact":
            return store.compact()
        if a.command == "retire":
            return store.retire(a.artifact, reason=a.reason)
        if a.command == "explain":
            return explain(store, a.artifact)
        if a.command == "graph":
            value = graph_data(
                store, focus=a.focus, view=a.view, limit=a.limit, baseline=a.baseline
            )
            output = (
                svg(value)
                if a.format == "svg"
                else (
                    mermaid(value)
                    if a.format == "mermaid"
                    else (
                        json.dumps(value, indent=2)
                        if a.format == "json"
                        else readable(value)
                    )
                )
            )
            if a.output:
                atomic_write(a.output, output.encode(), 0o644)
                return {
                    "graph": str(a.output.resolve()),
                    "shown": value["shown"],
                    "omitted": value["omitted"],
                }
            return output
        if a.command == "test-add":
            return publish_case(
                store,
                a.id,
                a.source.read_bytes(),
                path=a.path,
                visibility=a.visibility,
                obligations=a.obligation,
                expected_revision=a.revision,
            )
        if a.command == "suite":
            return suite(
                store,
                a.id,
                [store.ref(i) for i in a.cases],
                obligations=a.obligation,
                rationale=a.rationale,
                expected_revision=a.revision,
            )
        if a.command == "test-export":
            return materialize(
                store,
                store.ref(a.suite),
                a.directory,
                include_independent=a.include_independent,
            )
        engine = Engine(Repository(a.project), store, environments, a.work)
        if a.command == "run":
            from .automation import Automation
            automation = Automation(engine, read_json(a.config))
            return automation.watch(timeout=a.timeout, poll_seconds=a.poll_seconds) if a.watch else automation.run()
        if a.command == "sync-review":
            return engine.sync_remote_review()
        if a.command == "env-publish":
            release = read_json(a.release)
            return environments.register_release(
                engine, release["provider"], release["generation"]
            )
        if a.command == "env-accept":
            release = read_json(a.release)
            return environments.accept_release_subject(
                engine, release["provider"], release["generation"]
            )
        if a.command == "new":
            return engine.new(
                a.request,
                intake_permissions=(
                    read_json(a.permission_file) if a.permission_file else None
                ),
            )
        if a.command == "status":
            return engine.work
        if a.command == "propose":
            return engine.propose(
                read_json(a.blueprint), read_json(a.plan), a.consequence
            )
        if a.command == "provider-preflight":
            return engine.provider_preflight(read_json(a.selections))
        if a.command == "tester-preflight":
            return engine.tester_preflight(store.ref(a.suite), store.ref(a.job))
        if a.command in {
            "coder-preflight",
            "reconcile",
            "verified",
            "review",
            "diagnose",
            "import-planning",
            "import-test-design",
        }:
            return getattr(engine, a.command.replace("-", "_"))(store.ref(a.job))
        if a.command == "role":
            return engine.run_role(
                a.role,
                a.generation,
                a.action,
                suite_ref=store.ref(a.suite) if a.suite else None,
            )
        if a.command == "approve":
            return engine.approve(a.actor, a.digest, release=a.release)
        if a.command == "candidate":
            return engine.candidate(
                read_json(a.trace), subject=read_json(a.subject) if a.subject else None
            )
        if a.command == "verify":
            return engine.verify(a.environment, a.action, final=a.final)
        if a.command == "resume":
            return engine.resume(a.actor, repair_source=a.repair_source)
        if a.command == "publish-pr":
            return engine.publish_pull_request(
                a.actor, a.title, a.body_file.read_text()
            )
        if a.command == "ci":
            return engine.record_ci()
        if a.command == "promote":
            return engine.promote(remote_authorized=a.authorize_remote)
        if a.command in {"start", "accepting", "accept", "close", "recover-candidate", "recover-role"}:
            return getattr(engine, a.command.replace("-", "_"))()
        raise FrameworkError("unimplemented command")
    finally:
        store.close()
        environments.store.close()


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        result = execute(args)
        print(
            json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2)
            if args.json
            else readable(result)
        )
        return 0
    except (FrameworkError, OSError, ValueError, KeyError, TypeError) as exc:
        print(
            json.dumps({"error": str(exc)}) if args.json else "Blocked: " + str(exc),
            file=sys.stderr,
        )
        return 2


def project_main() -> int:
    return main()


def test_main() -> int:
    return main()


def scm_main() -> int:
    return main()


def hardware_main() -> int:
    return main([*sys.argv[1:], "hardware"])


if __name__ == "__main__":
    raise SystemExit(main())
