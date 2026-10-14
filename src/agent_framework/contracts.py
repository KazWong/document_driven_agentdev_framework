"""Structural and semantic contracts. Approval is never a role-supplied field."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from jsonschema import Draft202012Validator

from .common import FrameworkError, digest, read_json, safe_relative

DATA = Path(__file__).resolve().parent / "data"


def validate(definition: str, value: Any) -> None:
    schema = read_json(DATA / "contracts.schema.json")
    validator = Draft202012Validator(
        {"$defs": schema["$defs"], "$ref": "#/$defs/" + definition}
    )
    errors = sorted(validator.iter_errors(value), key=lambda e: str(list(e.path)))
    if errors:
        e = errors[0]
        raise FrameworkError(
            f"{definition} at {'.'.join(map(str, e.path)) or '<root>'}: {e.message}"
        )


def validate_blueprint(
    bp: dict[str, Any], previous: dict[str, Any] | None = None
) -> None:
    validate("Blueprint", bp)
    groups = [
        bp[k]
        for k in (
            "requirements",
            "components",
            "interfaces",
            "verification_obligations",
        )
    ]
    ids = [x["id"] for g in groups for x in g]
    if len(ids) != len(set(ids)):
        raise FrameworkError("Blueprint IDs must be globally unique")
    requirements = {x["id"] for x in bp["requirements"]}
    design = {x["id"] for x in bp["components"] + bp["interfaces"]}
    ver = {x["id"] for x in bp["verification_obligations"]}
    links = bp["traceability"]
    if (
        len(links) != len(requirements)
        or {x["requirement"] for x in links} != requirements
    ):
        raise FrameworkError("every requirement needs one traceability row")
    for link in links:
        if (
            not set(link["design_elements"]) <= design
            or not set(link["verifications"]) <= ver
        ):
            raise FrameworkError(
                "traceability contains unknown design/verification IDs"
            )
    if {v for l in links for v in l["verifications"]} != ver:
        raise FrameworkError("orphan verification obligation")
    fa = bp["final_acceptance"]
    if not set(fa["obligations"]) <= ver:
        raise FrameworkError("Final Acceptance must select existing VER obligations")
    envs = {x["id"] for x in bp["environment_requirements"]}
    if (
        len(envs) != len(bp["environment_requirements"])
        or not set(fa["required_environments"]) <= envs
    ):
        raise FrameworkError("invalid Final Acceptance environment matrix")
    if previous:
        if previous["project_id"] != bp["project_id"]:
            raise FrameworkError(
                "a Blueprint cannot change the managed project identity"
            )
        missing = {
            x["id"]
            for group in (
                "requirements",
                "components",
                "interfaces",
                "verification_obligations",
            )
            for x in previous[group]
        } - set(ids)
        retired = {
            i
            for row in bp["lineage"]
            if row["operation"] in {"retire", "split", "merge"}
            for i in row["ids"]
        }
        if missing - retired:
            raise FrameworkError(
                "replan silently removes original requirements: "
                + ", ".join(sorted(missing - retired))
            )


def validate_plan(plan: dict[str, Any], bp: dict[str, Any]) -> None:
    validate("Plan", plan)
    required = {"tasks", "scope", "risk_class", "permissions", "delivery"}
    if (
        not required <= set(plan)
        or set(plan) - required - {"scm", "environment_release"}
        or plan["delivery"] not in {"artifact", "scm"}
        or plan["risk_class"] not in {"R0", "R1", "R2", "R3"}
    ):
        raise FrameworkError(
            "plan requires tasks, scope, risk_class, permissions and delivery"
        )
    if plan["delivery"] == "scm":
        scm = plan.get("scm", {})
        if (
            not {"base_branch", "required_checks"} <= set(scm)
            or not scm["base_branch"]
            or not scm["required_checks"]
            or len(scm["required_checks"]) != len(set(scm["required_checks"]))
        ):
            raise FrameworkError(
                "SCM delivery must declare its base branch and required CI check names"
            )
    elif "scm" in plan:
        raise FrameworkError("artifact delivery cannot contain an SCM mutation policy")
    if "environment_release" in plan:
        release = plan["environment_release"]
        if set(release) != {
            "provider_contract",
            "environment_contract",
            "acceptance_action",
        }:
            raise FrameworkError(
                "environment release needs approved provider, environment and acceptance contracts"
            )
        action = release["acceptance_action"]
        if (
            set(action) != {"argv", "timeout_seconds", "permissions"}
            or not isinstance(action["argv"], list)
            or not action["argv"]
            or not 1 <= action["timeout_seconds"] <= 86400
        ):
            raise FrameworkError("invalid environment acceptance action")
        validate("Permissions", action["permissions"])
    validate("Permissions", plan["permissions"])
    scope = plan["scope"]
    if set(scope) != {"include", "exclude"} or not scope["include"]:
        raise FrameworkError("plan scope must include explicit allowed paths")
    for pattern in scope["include"] + scope["exclude"]:
        safe_relative(pattern)
    requirements = {x["id"] for x in bp["requirements"]}
    covered = set()
    task_ids = set()
    for task in plan["tasks"]:
        if (
            set(task) != {"id", "title", "requirements", "design", "paths"}
            or task["id"] in task_ids
        ):
            raise FrameworkError("invalid or duplicate Plan task")
        task_ids.add(task["id"])
        if not task["requirements"] or not set(task["requirements"]) <= requirements:
            raise FrameworkError("task refers to unknown requirements")
        design = {x["id"] for x in bp["components"] + bp["interfaces"]}
        if not task["design"] or not set(task["design"]) <= design:
            raise FrameworkError("task needs known Blueprint elements")
        for path in task["paths"]:
            safe_relative(path)
        covered.update(task["requirements"])
    mandatory = {x["id"] for x in bp["requirements"] if x["disposition"] == "required"}
    if not mandatory <= covered:
        raise FrameworkError("Plan does not cover all mandatory requirements")


def semantic_basis(bp: dict[str, Any], plan: dict[str, Any]) -> str:
    return digest({"blueprint": bp, "plan": plan})
