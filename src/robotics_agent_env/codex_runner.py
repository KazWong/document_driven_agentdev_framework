from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

from .constants import ROLE_ARTIFACT, ROLE_SANDBOX
from .util import (
    AgentEnvError, atomic_write_json, atomic_write_text, env_root, git,
    git_changed_paths, load_json, shell_join,
)
from .workitem import WorkItem


def _toml_string(value: str) -> str:
    return json.dumps(value)


def _load_role_instructions(role: str) -> str:
    path = env_root() / "config" / "roles" / f"{role}.md"
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise AgentEnvError(f"missing role instructions: {path}") from exc


def _latest_evidence(item: WorkItem) -> dict[str, Any]:
    collected: dict[str, Any] = {}
    for kind in ("local", "integration"):
        root = item.path / "evidence" / kind
        runs = sorted((path for path in root.iterdir() if path.is_dir()), reverse=True) if root.is_dir() else []
        if not runs:
            continue
        latest = runs[0]
        summary_path = latest / "summary.json"
        entry: dict[str, Any] = {"run": str(latest.relative_to(item.path))}
        if summary_path.is_file():
            entry["summary"] = load_json(summary_path)
        logs: dict[str, str] = {}
        for log_path in sorted(latest.rglob("*.log")):
            text = log_path.read_text(encoding="utf-8", errors="replace")
            logs[str(log_path.relative_to(item.path))] = text[-8000:]
            if len(logs) >= 6:
                break
        if logs:
            entry["log_tails"] = logs
        collected[kind] = entry
    return collected


def _git_context(item: WorkItem) -> dict[str, Any]:
    baseline = item.status.get("baseline_sha")
    context: dict[str, Any] = {"baseline_sha": baseline}
    if not baseline:
        return context
    try:
        context["changed_paths"] = git_changed_paths(item.repo, baseline=baseline)
        stat_result = git(item.repo, "diff", "--stat", baseline, check=False)
        context["diff_stat"] = stat_result.stdout[-12000:]
        check_result = git(item.repo, "diff", "--check", baseline, check=False)
        context["diff_check_returncode"] = check_result.returncode
        context["diff_check"] = (check_result.stdout + check_result.stderr)[-8000:]
    except AgentEnvError as exc:
        context["error"] = str(exc)
    return context


def _build_prompt(item: WorkItem, role: str, context: dict[str, Any] | None) -> str:
    artifacts = {
        path.name: path.read_text(encoding="utf-8")
        for path in sorted(item.artifacts_path.glob("*.md"))
    }
    payload = {
        "work_item": item.manifest,
        "workflow_status": item.status,
        "existing_artifacts": artifacts,
        "deterministic_evidence": _latest_evidence(item),
        "git_context": _git_context(item),
        "additional_context": context or {},
    }
    return f"""Execute the '{role}' responsibility for this agent-gated work item.

The work-item manifest is the authoritative scope. Do not silently expand it. Report a required scope change with scope_change=true and decision=blocked. Do not claim tests passed without deterministic evidence from the workflow.

Return exactly one JSON object matching the output schema. Put the substantive report in deliverable_markdown. Do not wrap the JSON in Markdown fences.

Context:
{json.dumps(payload, indent=2, sort_keys=True)}
"""


def dispatch_role(item: WorkItem, role: str, *, context: dict[str, Any] | None = None) -> dict[str, Any]:
    if role not in ROLE_SANDBOX:
        raise AgentEnvError(f"unknown agent role: {role}")
    run_dir = item.new_run_dir(role)
    result_path = run_dir / "result.json"
    prompt = _build_prompt(item, role, context)
    atomic_write_text(run_dir / "prompt.txt", prompt)
    instructions = _load_role_instructions(role)
    schema_path = env_root() / "schemas" / "agent-result.schema.json"
    codex_bin = os.environ.get("CODEX_BIN", "codex")
    command = [
        codex_bin, "--ask-for-approval", "never", "exec", "--cd", str(item.repo),
        "--sandbox", ROLE_SANDBOX[role], "--ephemeral", "--json",
        "--output-schema", str(schema_path), "--output-last-message", str(result_path),
        "--config", f"web_search={_toml_string('disabled')}",
        "--config", f"developer_instructions={_toml_string(instructions)}", "-",
    ]
    atomic_write_text(run_dir / "command.txt", shell_join(command) + "\n")
    allowed_env = {
        "HOME", "USER", "LOGNAME", "PATH", "LANG", "LC_ALL", "LC_CTYPE", "TERM",
        "COLORTERM", "NO_COLOR", "CI", "TMPDIR", "XDG_RUNTIME_DIR",
    }
    env = {key: value for key, value in os.environ.items() if key in allowed_env}
    env["CODEX_HOME"] = os.environ.get("CODEX_HOME", str(item.state_root / "codex-home"))
    try:
        completed = subprocess.run(
            command, cwd=str(item.repo), env=env, input=prompt, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=float(os.environ.get("AGENT_CODEX_TIMEOUT", "3600")), check=False,
        )
    except FileNotFoundError as exc:
        raise AgentEnvError(f"Codex CLI not found at '{codex_bin}'") from exc
    except subprocess.TimeoutExpired as exc:
        atomic_write_text(run_dir / "stderr.log", (exc.stderr or "") + "\nCodex run timed out.\n")
        result = _failure_result(role, "Codex run timed out")
        atomic_write_json(result_path, result)
        item.record_role_run(role, run_dir, result, 124)
        return result

    atomic_write_text(run_dir / "events.jsonl", completed.stdout)
    atomic_write_text(run_dir / "stderr.log", completed.stderr)
    if completed.returncode != 0:
        result = _failure_result(role, (completed.stderr.strip() or "Codex returned a non-zero exit status")[-2000:])
        atomic_write_json(result_path, result)
        item.record_role_run(role, run_dir, result, completed.returncode)
        return result
    try:
        raw = json.loads(result_path.read_text(encoding="utf-8"))
        result = validate_agent_result(raw)
    except (FileNotFoundError, json.JSONDecodeError, AgentEnvError) as exc:
        result = _failure_result(role, f"invalid or missing structured agent result: {exc}")
        atomic_write_json(result_path, result)
        item.record_role_run(role, run_dir, result, 2)
        return result
    item.record_role_run(role, run_dir, result, completed.returncode)
    deliverable = result.get("deliverable_markdown", "").strip()
    if deliverable:
        item.write_artifact(ROLE_ARTIFACT[role], deliverable)
    return result


def validate_agent_result(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise AgentEnvError("agent result must be a JSON object")
    required = {"status": str, "decision": str, "summary": str, "deliverable_markdown": str, "scope_change": bool, "findings": list, "evidence": list}
    for field, field_type in required.items():
        if field not in raw or not isinstance(raw[field], field_type):
            raise AgentEnvError(f"agent result field '{field}' has the wrong type")
    if raw["status"] not in {"completed", "blocked", "failed"}:
        raise AgentEnvError("invalid agent result status")
    if raw["decision"] not in {"pass", "fail", "blocked", "not_applicable"}:
        raise AgentEnvError("invalid agent result decision")
    for field in ("findings", "evidence"):
        if any(not isinstance(value, str) for value in raw[field]):
            raise AgentEnvError(f"agent result '{field}' entries must be strings")
    return raw


def _failure_result(role: str, detail: str) -> dict[str, Any]:
    return {
        "status": "failed", "decision": "fail", "summary": f"{role} execution failed",
        "deliverable_markdown": f"# {role.replace('_', ' ').title()} Failure\n\n{detail}",
        "scope_change": False, "findings": [detail], "evidence": [],
    }
