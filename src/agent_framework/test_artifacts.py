"""Tester-owned concrete cases; independent sources live only in the ledger CAS."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .common import (
    FrameworkError,
    atomic_write,
    bytes_digest,
    contained,
    digest,
    identifier,
    safe_relative,
)
from .store import Store


def publish_case(
    store: Store,
    case_id: str,
    source: bytes,
    *,
    path: str,
    visibility: str,
    obligations: list[str],
    expected_revision: int = 0,
) -> dict[str, Any]:
    identifier(case_id)
    safe_relative(path)
    if (
        visibility not in {"development", "independent"}
        or not obligations
        or len(obligations) != len(set(obligations))
    ):
        raise FrameworkError(
            "test cases require a visibility and unique public obligations"
        )
    for obligation in obligations:
        if store.head(obligation)["kind"] != "verification_obligation":
            raise FrameworkError("a test cannot introduce a new acceptance criterion")
    content = store.blob(source)
    return store.publish(
        case_id,
        "test_case",
        "tester",
        {
            "path": path,
            "visibility": visibility,
            "obligations": obligations,
            "content": content,
        },
        [(x, "verifies") for x in obligations],
        expected_revision=expected_revision,
    )


def suite(
    store: Store,
    suite_id: str,
    cases: list[dict[str, Any]],
    *,
    obligations: list[str],
    rationale: str,
    expected_revision: int = 0,
) -> dict[str, Any]:
    if not rationale.strip() or not cases or not obligations:
        raise FrameworkError(
            "test design needs cases, obligations and an allocation rationale"
        )
    paths = set()
    covered = set()
    independent = 0
    for ref in cases:
        record = store.resolve(ref, current=True)
        if record["kind"] != "test_case" or record["owner"] != "tester":
            raise FrameworkError("suite contains a non-Tester test artifact")
        case = record["payload"]
        if case["path"] in paths:
            raise FrameworkError("duplicate test path in suite")
        paths.add(case["path"])
        covered.update(case["obligations"])
        independent += case["visibility"] == "independent"
    if not set(obligations) <= covered or not independent:
        raise FrameworkError(
            "suite must cover its obligations and include independent checks"
        )
    return store.publish(
        suite_id,
        "suite",
        "tester",
        {
            "cases": cases,
            "obligations": sorted(set(obligations)),
            "allocation_rationale": rationale,
            "development_count": len(cases) - independent,
            "independent_count": independent,
        },
        [(r["id"], "derived_from") for r in cases],
        expected_revision=expected_revision,
    )


def materialize(
    store: Store, suite_ref: dict[str, Any], root: Path, *, include_independent: bool
) -> dict[str, str]:
    value = store.resolve(suite_ref, current=True)["payload"]
    inventory = {}
    for ref in value["cases"]:
        case = store.resolve(ref, current=True)["payload"]
        if case["visibility"] == "independent" and not include_independent:
            continue
        data = store.read_blob(case["content"])
        atomic_write(contained(root, case["path"]), data, 0o644)
        inventory[case["path"]] = bytes_digest(data)
    return inventory


def development_hashes(store: Store, suite_ref: dict[str, Any]) -> dict[str, str]:
    value = store.resolve(suite_ref, current=True)["payload"]
    return {
        case["path"]: case["content"]
        for case in (store.resolve(r, current=True)["payload"] for r in value["cases"])
        if case["visibility"] == "development"
    }
