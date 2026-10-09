"""Copy-on-write v2.0.3 history import; legacy source and approvals stay historical."""

from __future__ import annotations

import os
from pathlib import Path
import stat
from typing import Any

from .common import (
    Conflict,
    FrameworkError,
    bytes_digest,
    digest,
    locked,
    read_json,
    write_json,
)
from .store import Store


def inventory(source: Path) -> list[dict[str, Any]]:
    if not source.is_dir() or source.is_symlink():
        raise FrameworkError("legacy source must be a real directory")
    rows = []
    for path in sorted(source.rglob("*")):
        relative = path.relative_to(source)
        if (
            ".git" in relative.parts
            or "__pycache__" in relative.parts
            or ".pytest_cache" in relative.parts
        ):
            continue
        if path.is_symlink() or not (path.is_file() or path.is_dir()):
            raise FrameworkError(
                "unsupported legacy filesystem entry: " + str(relative)
            )
        if path.is_file():
            if path.name in {
                "auth.json",
                "credentials.json",
                ".env",
                "id_rsa",
                "id_ed25519",
            }:
                raise FrameworkError(
                    "select a legacy records directory without credentials: "
                    + str(relative)
                )
            rows.append(
                {
                    "path": relative.as_posix(),
                    "size": path.stat().st_size,
                    "mode": stat.S_IMODE(path.stat().st_mode),
                    "digest": bytes_digest(path.read_bytes()),
                }
            )
    return rows


def plan(source: Path, target: Path) -> dict[str, Any]:
    source = source.resolve()
    target = target.resolve()
    if (
        source == target
        or source.is_relative_to(target)
        or target.is_relative_to(source)
    ):
        raise FrameworkError(
            "migration requires disjoint legacy and new state directories"
        )
    rows = inventory(source)
    return {
        "migration_version": 1,
        "source_format": "v2.0.3",
        "source": str(source),
        "target": str(target),
        "input_manifest": rows,
        "input_digest": digest(rows),
        "conversion": "preserve exact source bytes as historical artifacts; start with no approvals or candidate evidence",
        "unresolved": [
            "Blueprint and requirement lineage",
            "approved environment/provider bindings",
            "current exact candidate",
            "ECP and release approvals",
        ],
        "result_state": "DRAFT",
        "dry_run": True,
    }


def apply(source: Path, target: Path, *, expected_digest: str) -> dict[str, Any]:
    proposal = plan(source, target)
    if proposal["input_digest"] != expected_digest:
        raise Conflict("legacy input changed since migration review")
    target = Path(proposal["target"])
    with locked(target.parent / (target.name + ".migration.lock")):
        if (target / "migration.json").exists():
            completed = read_json(target / "migration.json")
            if completed["input_digest"] != expected_digest:
                raise Conflict("target contains a different migration")
            with Store(target) as store:
                store.check_integrity()
            pointer = target.parent / (target.name + ".controller.json")
            # Recover a crash after the directory rename, but never undo an
            # operator's subsequent rollback by silently selecting v2.1 again.
            if not pointer.exists():
                _select(target, completed)
            return {
                **completed,
                "selected": read_json(pointer)["format"] == "v2.1.0",
                "already_applied": True,
            }
        pending = target.parent / (target.name + ".pending")
        pending.mkdir(parents=True, exist_ok=True)
        marker = pending / "migration-pending.json"
        if marker.exists() and read_json(marker)["input_digest"] != expected_digest:
            raise Conflict("pending migration was created from different source bytes")
        write_json(marker, proposal)
        with Store(pending) as store, store.transaction():
            for row in proposal["input_manifest"]:
                artifact_id = "LEGACY-" + digest(row["path"])[:32].upper()
                raw = (Path(proposal["source"]) / row["path"]).read_bytes()
                if bytes_digest(raw) != row["digest"]:
                    raise Conflict("legacy bytes changed during conversion")
                payload = {
                    **row,
                    "content": store.blob(raw),
                    "legacy_source": proposal["source"],
                    "historical_only": True,
                    "approval_authority": False,
                }
                if store.exists(artifact_id):
                    if store.get(artifact_id)["payload"] != payload:
                        raise Conflict(
                            "pending artifact disagrees with the input manifest"
                        )
                else:
                    store.publish(artifact_id, "legacy_artifact", "framework", payload)
            if not store.exists("MIGRATION-DRAFT"):
                store.publish(
                    "MIGRATION-DRAFT",
                    "migration",
                    "framework",
                    {
                        "state": "DRAFT",
                        "input_digest": expected_digest,
                        "unresolved": proposal["unresolved"],
                    },
                )
            store.check_integrity()
        if digest(inventory(Path(proposal["source"]))) != expected_digest:
            raise Conflict("legacy source changed before migration selection")
        complete = {**proposal, "dry_run": False, "selected": True}
        write_json(pending / "migration.json", complete)
        if target.exists():
            raise Conflict(
                "migration target exists and is not a completed matching migration"
            )
        os.replace(pending, target)
        fd = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
        _select(target, complete)
        return complete


def _select(target: Path, proposal: dict[str, Any]) -> None:
    write_json(
        target.parent / (target.name + ".controller.json"),
        {
            "format": "v2.1.0",
            "state_root": str(target),
            "previous": {"format": "v2.0.3", "state_root": proposal["source"]},
            "migration_digest": proposal["input_digest"],
        },
    )


def rollback(target: Path, *, actor: str) -> dict[str, Any]:
    if not actor.strip():
        raise FrameworkError("rollback requires an operator identity")
    target = target.resolve()
    with locked(target.parent / (target.name + ".migration.lock")):
        pointer = target.parent / (target.name + ".controller.json")
        current = read_json(pointer)
        if current["format"] == "v2.0.3":
            return {**current, "already_rolled_back": True}
        value = {
            **current["previous"],
            "preserved_v21_state": str(target),
            "rollback_actor": actor,
        }
        write_json(pointer, value)
        with Store(target) as store:
            store.event("migration_rolled_back", {"actor": actor, "selected": value})
        return value
