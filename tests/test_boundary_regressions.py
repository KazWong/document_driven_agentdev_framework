"""Controller boundary tests using local Git and explicit command doubles."""
import copy
from dataclasses import replace
from pathlib import Path
import sys

import pytest

from agent_framework.common import Conflict, FrameworkError, digest
from agent_framework.docker_backend import DockerBackend
from agent_framework.execution import ProcessExecutor
from agent_framework.remote import BitbucketDelivery, delivery_for
from agent_framework.store import Store
from test_execution import DockerCommands, request
from test_remote_providers import API, PR, SHA


@pytest.mark.parametrize('target', ['/context/..', '/credentials/../../etc', '/tests/./data'])
def test_docker_mount_targets_cannot_traverse_reserved_roots(tmp_path, target):
    r = request(tmp_path)
    with pytest.raises(FrameworkError, match='mount target'):
        DockerBackend(DockerCommands()).execute(replace(r, read_only={target: r.project}))


def test_docker_preserves_explicit_tls_client_configuration(tmp_path, monkeypatch):
    for k, v in {'DOCKER_TLS_VERIFY': '1', 'DOCKER_CERT_PATH': '/private/docker-certs',
                 'DOCKER_CONFIG': '/private/docker-config'}.items():
        monkeypatch.setenv(k, v)
    class Capture(DockerCommands):
        def run(self, argv, **kwargs):
            self.environ = kwargs.get('env', {})
            return super().run(argv, **kwargs)
    c = Capture()
    DockerBackend(c).execute(request(tmp_path))
    assert c.environ['DOCKER_TLS_VERIFY'] == '1'
    assert c.environ['DOCKER_CERT_PATH'] == '/private/docker-certs'
    assert c.environ['DOCKER_CONFIG'] == '/private/docker-config'


def test_git_preserves_ssh_agent_only_in_trusted_git_commands(workflow, monkeypatch):
    e, _, _ = workflow
    monkeypatch.setenv('SSH_AUTH_SOCK', '/private/ssh-agent.sock')
    original = e.repo.executor
    class Capture:
        def run(self, argv, **kwargs):
            self.environ = kwargs.get('env', {})
            return original.run(argv, **kwargs)
    c = Capture()
    e.repo.executor = c
    assert e.repo.head
    assert c.environ['SSH_AUTH_SOCK'] == '/private/ssh-agent.sock'
    assert c.environ['GIT_LITERAL_PATHSPECS'] == '1'
    assert c.environ['GIT_TERMINAL_PROMPT'] == '0'
    # The socket is not a new blanket ProcessExecutor inheritance permission.
    assert ProcessExecutor().run([sys.executable, '-c', 'import os;print(os.getenv("SSH_AUTH_SOCK"))']).stdout.strip() == 'None'


def test_git_stages_literal_colon_filename(workflow):
    e, _, _ = workflow
    repo = e.repo
    repo.git('checkout', '-b', 'agent/literal')
    path = ':(glob)literal.txt'
    (repo.path / path).write_text('literal filename\n')
    base = repo.head
    result = repo.candidate(base, base, {'include': ['*'], 'exclude': []}, {}, 'Literal path')
    assert path in repo.files(result)


def test_candidate_reverting_all_work_is_rejected_before_commit(workflow):
    e, _, _ = workflow
    repo = e.repo
    repo.git('checkout', '-b', 'agent/revert')
    base = repo.head
    (repo.path / 'app.txt').write_text('first change\n')
    first = repo.candidate(base, base, {'include': ['app.txt'], 'exclude': []}, {}, 'First')
    (repo.path / 'app.txt').write_text('original\n')
    with pytest.raises(FrameworkError, match='baseline'):
        repo.candidate(base, first, {'include': ['app.txt'], 'exclude': []}, {}, 'No effective change')
    assert repo.head == first


def test_every_git_push_destination_is_authorized(workflow):
    e, _, _ = workflow
    e.repo.git('remote', 'add', 'origin', 'https://github.com/owner/repo.git')
    e.repo.git('remote', 'set-url', '--add', '--push', 'origin', 'https://github.com/owner/repo.git')
    e.repo.git('remote', 'set-url', '--add', '--push', 'origin', 'https://github.com/unapproved/repo.git')
    with pytest.raises(Conflict, match='origin'):
        delivery_for(e.repo, {'provider': 'github', 'repository': 'owner/repo', 'human_reviewers': ['human']})


def test_bitbucket_revocation_during_comment_fetch_is_rejected():
    class RevokingAPI(API):
        def pages(self, path):
            result = super().pages(path)
            self.value['participants'][0]['approved'] = False
            return result
    d = BitbucketDelivery(None, 'owner/repo', RevokingAPI())
    d.reviewers = ['human']
    with pytest.raises(Conflict, match='approval|review'):
        d.review(PR, SHA)


def test_private_state_refuses_world_readable_existing_directory(tmp_path):
    root = tmp_path / 'public-state'
    root.mkdir(mode=0o755)
    with pytest.raises(FrameworkError, match='private|owner-only'):
        with Store(root):
            pass
    assert not (root / 'ledger.sqlite3').exists()


def test_old_environment_generation_can_be_retired_after_provider_update(workflow):
    e, _, _ = workflow
    env = e.environments
    contract = copy.deepcopy(env.provider('test-provider'))
    contract['provider_version'] = '2.0.0'
    env._register_provider(contract, {'test_only': True})
    env.retire('ENV-001')
    assert env.gc()['generations'] == ['ENV-001']


def test_active_environment_base_cannot_be_retired(workflow):
    e, _, _ = workflow
    env = e.environments
    parent = env.get('ENV-001')
    child = {k: parent[k] for k in ('id', 'backend', 'artifact_digest', 'provider_id',
                                   'provider_digest', 'capabilities', 'constraints', 'base_generations')}
    child.update(id='ENV-CHILD', artifact_digest='sha256:' + '4' * 64, base_generations=['ENV-001'])
    with env.store.transaction():
        env._generation(child, {'test_only': True})
    with pytest.raises(Conflict, match='base|depend'):
        env.retire('ENV-001')
    assert env.get('ENV-CHILD')['status'] == 'promoted'
