"""Optional operator-installed Docker sandbox compatibility profile.

This is a trusted deployment input, never a role output or agent-controlled file.
No unconfined/privileged fallback is available.
"""
from pathlib import Path
import re
from .common import FrameworkError, bytes_digest, read_json


def security_options(config_path, request):
    if config_path is None:
        return []
    path = Path(config_path).resolve()
    for root in (request.project.resolve(), request.output.resolve()):
        if path.is_relative_to(root):
            raise FrameworkError('runtime profile must be outside agent-visible writable directories')
    config = read_json(path)
    if config['image'] != request.image or config['argv'] != request.argv:
        return []
    apparmor = config['apparmor']
    if not re.fullmatch(r'agent-fw-[A-Za-z0-9_-]+', apparmor):
        raise FrameworkError('runtime profile requires a named agent-fw AppArmor policy')
    seccomp = Path(config['seccomp_path']).resolve()
    proof = Path(config['proof_path']).resolve()
    for file, key in ((seccomp, 'seccomp_sha256'), (proof, 'proof_sha256')):
        if not file.is_file() or bytes_digest(file.read_bytes()) != config[key]:
            raise FrameworkError('runtime profile file is missing or changed: ' + key)
        if file.is_relative_to(request.project.resolve()) or file.is_relative_to(request.output.resolve()):
            raise FrameworkError('runtime profile files must be controller-owned')
    policy = read_json(seccomp)
    if policy.get('defaultAction') not in {'SCMP_ACT_ERRNO', 'SCMP_ACT_KILL', 'SCMP_ACT_KILL_PROCESS'}:
        raise FrameworkError('runtime seccomp must deny by default')
    evidence = read_json(proof)
    process = evidence.get('process', {})
    lines = process.get('stdout', '').splitlines()
    if (not evidence.get('prepared') or evidence.get('backend') != 'docker'
            or evidence.get('artifact_digest') != request.image
            or process.get('returncode') != 0 or process.get('timed_out') or process.get('output_limited')
            or not {'BWRAP_READ_ONLY_PASS', 'BWRAP_WORKSPACE_WRITE_PASS', 'BWRAP_PROBE_PASS'} <= set(lines)):
        raise FrameworkError('runtime profile requires a passing sandbox probe for the exact image')
    return ['--security-opt', 'apparmor=' + apparmor, '--security-opt', 'seccomp=' + str(seccomp)]
