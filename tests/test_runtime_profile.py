import json
import pytest
from agent_framework.runtime_profile import security_options
from agent_framework.common import FrameworkError, bytes_digest
from test_execution import request, DockerCommands
from agent_framework.docker_backend import DockerBackend

def test_workspace_can_execute_build_products_without_relaxing_other_mounts(tmp_path):
    commands = DockerCommands()
    DockerBackend(commands).execute(request(tmp_path))
    create = next(x for x in commands.calls if x[1] == 'create')
    assert '/work:rw,exec,nosuid,nodev,size=256m,mode=1777' in create
    assert '/tmp:rw,noexec,nosuid,size=64m' in create
    assert '--privileged' not in create and '--cap-add' not in create
    assert 'no-new-privileges:true' in create

def test_runtime_profile_requires_exact_successful_proof(tmp_path):
    req = request(tmp_path)
    seccomp = tmp_path / 'seccomp.json'
    seccomp.write_text(json.dumps({'defaultAction': 'SCMP_ACT_ERRNO'}))
    proof = tmp_path / 'proof.json'
    data = {'backend': 'docker', 'prepared': True, 'artifact_digest': req.image,
            'process': {'returncode': 0, 'timed_out': False, 'output_limited': False,
                        'stdout': 'BWRAP_READ_ONLY_PASS\nBWRAP_WORKSPACE_WRITE_PASS\nBWRAP_PROBE_PASS'}}
    proof.write_text(json.dumps(data))
    config = {'image': req.image, 'argv': req.argv, 'apparmor': 'agent-fw-test',
              'seccomp_path': str(seccomp), 'seccomp_sha256': bytes_digest(seccomp.read_bytes()),
              'proof_path': str(proof), 'proof_sha256': bytes_digest(proof.read_bytes())}
    path = tmp_path / 'profile.json'
    path.write_text(json.dumps(config))
    assert 'apparmor=agent-fw-test' in security_options(path, req)
    proof.write_text('{}')
    with pytest.raises(FrameworkError, match='changed'): security_options(path, req)
