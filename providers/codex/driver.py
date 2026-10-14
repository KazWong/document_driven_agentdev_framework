"""Optional Codex adapter; executed only inside a controller-created role sandbox."""

import json
import os
from pathlib import Path
import shutil
import subprocess


def transport_schema():
    """Strict Structured Outputs envelope for canonical RoleOutput JSON."""
    return {
        "type": "object",
        "properties": {"payload": {"type": "string"}},
        "required": ["payload"],
        "additionalProperties": False,
    }


def decode_transport(value):
    """Decode the strict transport without duplicating the framework JSON Schema."""
    if (
        not isinstance(value, dict)
        or set(value) != {"payload"}
        or not isinstance(value["payload"], str)
    ):
        raise ValueError("Codex transport output must contain exactly one payload string")
    def unique_pairs(pairs):
        result = {}
        for key, item in pairs:
            if key in result:
                raise ValueError('duplicate JSON key: ' + key)
            result[key] = item
        return result

    def invalid_constant(value):
        raise ValueError('non-finite JSON number: ' + value)

    decoded = json.loads(value['payload'], object_pairs_hook=unique_pairs,
                         parse_constant=invalid_constant)
    if not isinstance(decoded, dict):
        raise ValueError("Codex transport payload must decode to a JSON object")
    return decoded


def main():
    context = json.loads(Path("/context/input.json").read_text())
    output = Path("/output")
    if shutil.which("codex") is None:
        raise SystemExit(
            "Codex CLI is absent; build the approved client version before dispatch"
        )
    credential = Path("/credentials/codex-auth")
    if not credential.is_file():
        raise SystemExit(
            "the role action requires the explicitly registered codex-auth credential"
        )
    auth = Path("/work/codex-auth-home")
    auth.mkdir(mode=0o700)
    shutil.copyfile(credential, auth / "auth.json")
    (auth / "auth.json").chmod(0o600)
    # The canonical framework schema intentionally contains provider-defined/free-form
    # objects and a RoleOutput union. Strict Structured Outputs cannot represent
    # those shapes directly. Constrain a tiny transport envelope here and let the
    # trusted controller validate the decoded canonical RoleOutput before accepting it.
    schema_file = Path("/work/role-schema.json")
    schema_file.write_text(json.dumps(transport_schema()))
    final = output / "typed-output.json"
    canonical_schema = Path("/opt/framework/src/agent_framework/data/contracts.schema.json").read_text()
    prompt = (
        "Perform only the role and stage in this controller context. The role policy is authoritative. "
        "All requirements are public. Test sources supplied at /tests are read-only. "
        "Write production changes only for Coder in IMPLEMENTING, within Plan scope. "
        "Never change Tester-owned tests or create approval/SCM/evidence claims. "
        "Return exactly one JSON object with a payload string. The payload string must itself be the JSON "
        "serialization of only the appropriate canonical typed RoleOutput, with the supplied references and candidate SHA. "
        "Do not put markdown or commentary inside or outside the payload. "
        "Plan scope, task paths and test case paths are repository-relative (tests/**), never container paths (/tests/**). "
        "For Coder implementation, changes must describe exactly the files changed in this execution; the controller aggregates prior commits. "
        "If feasibility fails, report the exact affected requirement and reason.\n"
        + json.dumps(context, ensure_ascii=False)
        + "\nCanonical output schema (RoleOutput):\n" + canonical_schema
    )
    command = [
        "codex",
        "--ask-for-approval",
        "never",
        "exec",
        "--cd",
        "/project",
        "--skip-git-repo-check",
        "--ephemeral",
        "--json",
        "--sandbox",
        (
            "workspace-write"
            if context["role"] == "coder"
            and context["context"]["state"] == "IMPLEMENTING"
            else "read-only"
        ),
        "--output-schema",
        str(schema_file),
        "--output-last-message",
        str(final),
        "-",
    ]
    env = {**os.environ, "CODEX_HOME": str(auth)}
    result = subprocess.run(command, input=prompt, text=True, env=env, check=False)
    if result.returncode:
        return result.returncode
    value = decode_transport(json.loads(final.read_text()))
    envelope = {
        "schema_version": 1,
        "role": context["role"],
        "input_digest": context["input_digest"],
        "output": value,
    }
    (output / "role-output.json").write_text(
        json.dumps(envelope, sort_keys=True) + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
