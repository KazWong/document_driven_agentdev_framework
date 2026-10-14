"""Real filesystem/SQLite/Git interruption tests; no live agent or container claim."""
from pathlib import Path
import os
import subprocess
import sys

import pytest

from agent_framework.automation import Automation
from agent_framework.common import Conflict
from agent_framework import worktree_apply
from agent_framework.roles import inventory
from agent_framework.store import Store
from conftest import preflight
from test_automation_concurrency import CONFIG


def implementing(workflow):
    e, backend, suite = workflow
    preflight(e, suite)
    e.approve('human', e.work['package']['digest'])
    e.start()
    return e, backend


@pytest.mark.parametrize('kind', ['role_output', 'automation_receipt'])
def test_failed_publication_rolls_back_all_coder_files(workflow, monkeypatch, kind):
    e, _ = implementing(workflow)
    original = Store.publish
    def fail(self, artifact_id, record_kind, *args, **kwargs):
        if record_kind == kind:
            raise OSError('injected ledger write failure')
        return original(self, artifact_id, record_kind, *args, **kwargs)
    monkeypatch.setattr(Store, 'publish', fail)
    before = e.repo.head
    with pytest.raises(OSError, match='injected'):
        Automation(e, CONFIG)._role('coder')
    assert e.repo.clean()
    assert e.repo.head == before
    assert (e.repo.path / 'app.txt').read_text() == 'original\n'
    assert not list(e.store.root.glob('role-apply-*.json'))
    assert not e.store.list(kind='automation_receipt')


def test_completed_coder_dispatch_is_not_reexecuted_after_restart(workflow):
    e, backend = implementing(workflow)
    ref = Automation(e, CONFIG)._role('coder')
    calls = len(backend.requests)
    assert not e.repo.clean()
    assert Automation(e, CONFIG)._role('coder') == ref
    assert len(backend.requests) == calls
    assert len(e.store.list(kind='automation_receipt')) == 1
    assert e.store.check_integrity()['records'] > 0


def prepare_delta(e, tmp_path):
    source = tmp_path / 'replacement'
    source.mkdir()
    (source / 'app.txt').write_text('replacement\n')
    (source / 'new.txt').write_text('new file\n')
    return worktree_apply.prepare(e.store, e.repo, 'JOB-INTERRUPTION',
                                  ['app.txt', 'new.txt'], source, inventory(source))


@pytest.mark.parametrize('committed', [False, True])
def test_recovery_rolls_back_uncommitted_but_retains_committed_delta(workflow, tmp_path, committed):
    e, _ = implementing(workflow)
    journal, value = prepare_delta(e, tmp_path)
    worktree_apply.apply(e.store, e.repo, value)
    if committed:
        e.store.publish(value['job'], 'role_output', 'coder', {'simulated_commit': True})
    result = e.recover_role()
    assert result['recovered'] == [{'job': value['job'], 'action': 'completed' if committed else 'rolled_back'}]
    assert (e.repo.path / 'app.txt').read_text() == ('replacement\n' if committed else 'original\n')
    assert (e.repo.path / 'new.txt').exists() == committed
    assert not journal.exists()
    assert e.recover_role() == {'recovered': []}


def test_unknown_external_edit_is_not_overwritten_by_recovery(workflow, tmp_path):
    e, _ = implementing(workflow)
    journal, value = prepare_delta(e, tmp_path)
    worktree_apply.apply(e.store, e.repo, value)
    (e.repo.path / 'app.txt').write_text('external user edit\n')
    with pytest.raises(Conflict, match='unknown external edit'):
        e.recover_role()
    assert (e.repo.path / 'app.txt').read_text() == 'external user edit\n'
    assert journal.exists()


@pytest.mark.parametrize('direction', ['file_to_directory', 'directory_to_file'])
def test_file_directory_replacements_are_reversible(workflow, tmp_path, direction):
    e, _ = implementing(workflow)
    source = tmp_path / 'replacement'
    source.mkdir()
    if direction == 'file_to_directory':
        (source / 'app.txt').mkdir()
        (source / 'app.txt' / 'child').write_text('new child\n')
    else:
        (e.repo.path / 'app.txt').unlink()
        (e.repo.path / 'app.txt').mkdir()
        (e.repo.path / 'app.txt' / 'child').write_text('old child\n')
        (source / 'app.txt').write_text('new parent\n')
    before = inventory(e.repo.path)
    # Repository inventory includes .git metadata; only these two paths are touched.
    journal, value = worktree_apply.prepare(e.store, e.repo, 'JOB-REPLACEMENT',
                         ['app.txt', 'app.txt/child'], source, inventory(source))
    worktree_apply.apply(e.store, e.repo, value)
    worktree_apply.rollback(e.store, e.repo, value)
    assert inventory(e.repo.path) == before
    journal.unlink()


def test_process_exit_mid_transaction_is_recovered_from_durable_journal(workflow, tmp_path):
    e, _ = implementing(workflow)
    journal, value = prepare_delta(e, tmp_path)
    script = '''
import os,sys
from pathlib import Path
from agent_framework.common import read_json
from agent_framework.scm import Repository
from agent_framework.store import Store
from agent_framework.worktree_apply import apply
store=Store(Path(sys.argv[1]))
repo=Repository(Path(sys.argv[2]))
value=read_json(Path(sys.argv[3]))
with store.transaction():
    apply(store,repo,value)
    store.publish(value['job'],'role_output','coder',{'not_committed':True})
    os._exit(91)
'''
    env = {**os.environ, 'PYTHONPATH': str(Path(__file__).parents[1] / 'src')}
    result = subprocess.run([sys.executable, '-c', script, str(e.store.root),
                             str(e.repo.path), str(journal)], env=env, timeout=15)
    assert result.returncode == 91
    assert not e.store.exists(value['job'])
    assert (e.repo.path / 'app.txt').read_text() == 'replacement\n'
    assert e.recover_role()['recovered'][0]['action'] == 'rolled_back'
    assert e.repo.clean()
    assert not journal.exists()
