from pathlib import Path
import json

import pytest

from agent_framework.cli import main
from agent_framework.common import Conflict, FrameworkError, read_json
from agent_framework import migration
from agent_framework.store import Store


def test_migration_dry_run_exact_bytes_idempotence_and_rollback(tmp_path):
    source = tmp_path / "legacy"
    source.mkdir()
    (source / "history.json").write_text(
        '{"state":"MERGED","role":"integration_tester"}\n'
    )
    (source / "run.sh").write_text("#!/bin/sh\nexit 0\n")
    (source / "run.sh").chmod(0o755)
    target = tmp_path / "v21"
    planned = migration.plan(source, target)
    assert not target.exists()
    original = migration.inventory(source)
    result = migration.apply(source, target, expected_digest=planned["input_digest"])
    assert result["result_state"] == "DRAFT" and migration.inventory(source) == original
    with Store(target) as store:
        assert not store.list("approval") and not store.list("verification_result")
        for row in store.list("legacy_artifact"):
            value = store.get(row["id"])["payload"]
            assert (
                store.read_blob(value["content"])
                == (source / value["path"]).read_bytes()
            )
    assert migration.apply(source, target, expected_digest=planned["input_digest"])[
        "already_applied"
    ]
    rolled = migration.rollback(target, actor="operator")
    assert (
        rolled["format"] == "v2.0.3"
        and target.exists()
        and migration.inventory(source) == original
    )


def test_migration_rejects_input_change_and_overlapping_paths(tmp_path):
    source = tmp_path / "legacy"
    source.mkdir()
    (source / "file").write_text("before")
    planned = migration.plan(source, tmp_path / "new")
    (source / "file").write_text("after")
    with pytest.raises(Conflict):
        migration.apply(
            source, tmp_path / "new", expected_digest=planned["input_digest"]
        )
    with pytest.raises(FrameworkError):
        migration.plan(source, source / "new")


def test_migration_resumes_interrupted_pending_store(tmp_path):
    source = tmp_path / "legacy"
    source.mkdir()
    (source / "file").write_bytes(b"evidence")
    target = tmp_path / "new"
    planned = migration.plan(source, target)
    pending = tmp_path / "new.pending"
    pending.mkdir()
    from agent_framework.common import write_json

    write_json(pending / "migration-pending.json", planned)
    with Store(pending) as s:
        s.event("interrupted_import", {})
    migration.apply(source, target, expected_digest=planned["input_digest"])
    assert not pending.exists() and (target / "migration.json").is_file()


def test_neutral_project_cli_and_readable_status(tmp_path, capsys):
    product = tmp_path / "product"
    assert main(["--project", str(product), "init", "--id", "PROJECT-CLI"]) == 0
    assert set(p.name for p in product.iterdir()) == {".git", "project.json"}
    state = tmp_path / "state"
    base = ["--project", str(product), "--state", str(state)]
    assert main([*base, "new", "Create a tool"]) == 0
    capsys.readouterr()
    assert main([*base, "status"]) == 0
    output = capsys.readouterr().out
    assert "State: INTAKE" in output and not output.startswith("{")
    assert main([*base, "--json", "status"]) == 0
    assert json.loads(capsys.readouterr().out)["state"] == "INTAKE"


def test_removed_roles_and_hardware_fail_closed(capsys):
    with pytest.raises(SystemExit):
        main(["role", "integration_tester"])
    assert main(["hardware"]) == 2
    assert "automatic physical execution is disabled" in capsys.readouterr().err


def test_migration_recovers_rename_before_pointer_without_undoing_rollback(
    tmp_path, monkeypatch
):
    source = tmp_path / "legacy"
    source.mkdir()
    (source / "file").write_text("history")
    target = tmp_path / "new"
    proposal = migration.plan(source, target)
    original = migration._select

    def crash(*args):
        raise OSError("simulated interruption after rename")

    monkeypatch.setattr(migration, "_select", crash)
    with pytest.raises(OSError):
        migration.apply(source, target, expected_digest=proposal["input_digest"])
    assert (target / "migration.json").is_file()
    monkeypatch.setattr(migration, "_select", original)
    assert migration.apply(source, target, expected_digest=proposal["input_digest"])[
        "selected"
    ]
    migration.rollback(target, actor="operator")
    assert not migration.apply(
        source, target, expected_digest=proposal["input_digest"]
    )["selected"]
