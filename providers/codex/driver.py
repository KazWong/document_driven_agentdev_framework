"""Optional Codex adapter; executed only inside a controller-created role sandbox."""

import json
import os
from pathlib import Path
import shutil
import subprocess


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
    definitions = json.loads(
        Path(
            "/opt/framework/src/agent_framework/data/contracts.schema.json"
        ).read_text()
    )["$defs"]
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$defs": definitions,
        "$ref": "#/$defs/RoleOutput",
    }
    schema_file = Path("/work/role-schema.json")
    schema_file.write_text(json.dumps(schema))
    final = output / "typed-output.json"
    prompt = (
        "Perform only the role and stage in this controller context. The role policy is authoritative. "
        "All requirements are public. Test sources supplied at /tests are read-only. "
        "Write production changes only for Coder in IMPLEMENTING, within Plan scope. "
        "Never change Tester-owned tests or create approval/SCM/evidence claims. "
        "Return only the appropriate typed RoleOutput, with the supplied references and candidate SHA. "
        "If feasibility fails, report the exact affected requirement and reason.\n"
        + json.dumps(context, ensure_ascii=False)
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
    value = json.loads(final.read_text())
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
