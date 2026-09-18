from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_auth_service_is_opt_in_host_networked_and_docker_socket_free():
    compose = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))
    auth = compose["services"]["codex-login"]
    assert auth["profiles"] == ["auth"]
    assert auth["network_mode"] == "host"
    assert not any(
        isinstance(mount, dict) and mount.get("source") == "/var/run/docker.sock"
        for mount in auth["volumes"]
    )
    assert auth["environment"]["CODEX_HOME"].endswith("/.agent-state/codex-home")


def test_login_helper_supports_all_three_authentication_modes():
    text = (ROOT / "scripts/codex-login.sh").read_text(encoding="utf-8")
    assert "codex login\n" in text or "codex login\"" in text
    assert "codex login --device-auth" in text
    assert "codex login --with-api-key" in text
    assert "OPENAI_API_KEY" in text
    assert "ssh -L 1455:127.0.0.1:1455" in text


def test_api_key_is_piped_over_stdin_not_used_as_command_argument():
    text = (ROOT / "scripts/codex-login.sh").read_text(encoding="utf-8")
    api_section = text.split("api-key)", 1)[1].split("status)", 1)[0]
    assert "printf '%s\\n' \"$OPENAI_API_KEY\"" in api_section
    assert "--with-api-key" in api_section
    assert "--api-key=$OPENAI_API_KEY" not in api_section
    assert "--api-key \"$OPENAI_API_KEY\"" not in api_section


def test_api_key_runtime_invocation_keeps_secret_out_of_argv(tmp_path, monkeypatch):
    import os
    import subprocess

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    log = tmp_path / "argv.txt"
    stdin_log = tmp_path / "stdin.txt"
    docker = fake_bin / "docker"
    docker.write_text(
        "#!/usr/bin/env bash\n"
        f"printf '%s\\n' \"$@\" > {log!s}\n"
        f"cat > {stdin_log!s}\n",
        encoding="utf-8",
    )
    docker.chmod(0o755)
    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    env["OPENAI_API_KEY"] = "sk-test-secret-value"
    completed = subprocess.run(
        [str(ROOT / "scripts/codex-login.sh"), "api-key"],
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert completed.returncode == 0
    argv = log.read_text(encoding="utf-8")
    stdin = stdin_log.read_text(encoding="utf-8")
    assert "sk-test-secret-value" not in argv
    assert "login" in argv
    assert "--with-api-key" in argv
    assert stdin.strip() == "sk-test-secret-value"
