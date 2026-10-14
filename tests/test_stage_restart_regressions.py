"""Stage-specific role rejections and Git intent restart behavior."""
import pytest

from agent_framework.automation import Automation
from agent_framework.common import Conflict, FrameworkError, read_json, write_json
from conftest import changes
from test_automation_concurrency import CONFIG, ParallelBackend
from test_recovery_regressions import implementing


class BadStageOnce(ParallelBackend):
    def __init__(self, defect):
        super().__init__()
        self.defect, self.injected = defect, False

    def execute(self, request):
        data = read_json(request.read_only['/context'] / 'input.json')
        result = super().execute(request)
        path = request.output / 'role-output.json'
        if not path.exists() or self.injected:
            return result
        response = read_json(path)
        value = response['output']
        kind = value['artifact_type']
        defect = self.defect
        if kind == 'test_design_draft' and defect == 'unknown_obligation':
            value['cases'][0]['obligations'] = ['VER-UNKNOWN']
        elif kind == 'test_design_draft' and defect == 'absolute_test_path':
            value['cases'][0]['path'] = '/tests/test_bad.py'
        elif kind == 'test_design_draft' and defect == 'out_of_scope_tests':
            value['cases'][0]['path'] = 'unauthorized/test_bad.py'
        elif kind == 'test_design_draft' and defect == 'wrong_stage':
            value.clear()
            value.update(role='tester', artifact_type='testability',
                         test_design_ref=data['context']['package_ref'], feasible=True, findings=[])
        elif kind == 'testability' and defect == 'unexplained_infeasibility':
            value.update(feasible=False, findings=[])
        elif kind == 'implementation_feasibility' and data['context']['state'] == 'TESTER_FEASIBLE' and defect == 'wrong_handoff':
            value['handoff_ref'] = value['package_ref']
        elif kind == 'planning' and defect == 'reconciliation_findings':
            value['findings'] = ['REQ-001 requires a corrected Plan']
        elif kind == 'planning' and defect == 'missing_reconciliation':
            value['requirement_reconciliation'] = ['REQ-UNKNOWN']
        else:
            return result
        self.injected = True
        write_json(path, response)
        return result


@pytest.mark.parametrize('defect', ['unknown_obligation', 'absolute_test_path', 'out_of_scope_tests',
                                  'wrong_stage', 'unexplained_infeasibility', 'wrong_handoff',
                                  'reconciliation_findings', 'missing_reconciliation'])
def test_preapproval_rejection_gets_bounded_replan_not_permanent_cached_failure(workflow, defect):
    e, _, _ = workflow
    backend = BadStageOnce(defect)
    e.environments.backends[backend.name] = backend
    result = Automation(e, CONFIG).run()
    assert backend.injected
    assert result['state'] == 'APPROVAL_READY'
    assert len(e.work['failures']) == 1
    assert e.work['automatic_replans'] == 1
    assert not e.work['approvals']
    assert e.repo.clean()


def interrupt_before_commit(e, monkeypatch):
    git = e.repo.git
    def interrupted(*args, **kwargs):
        if 'commit' in args:
            raise RuntimeError('interruption before Git commit')
        return git(*args, **kwargs)
    monkeypatch.setattr(e.repo, 'git', interrupted)
    with pytest.raises(RuntimeError, match='before Git commit'):
        e.candidate(changes())
    monkeypatch.setattr(e.repo, 'git', git)


def test_precommit_intent_can_be_recovered_without_rerunning_coder(workflow, monkeypatch):
    e, _ = implementing(workflow)
    Automation(e, CONFIG)._role('coder')
    interrupt_before_commit(e, monkeypatch)
    assert e.work['state'] == 'IMPLEMENTING' and not e.repo.clean()
    ref = e.recover_candidate()
    assert e.work['candidate'] == ref
    assert e.repo.clean()
    assert not list(e.store.root.glob('candidate-intent-*.json'))


def test_precommit_recovery_rejects_unknown_external_edit(workflow, monkeypatch):
    e, _ = implementing(workflow)
    Automation(e, CONFIG)._role('coder')
    interrupt_before_commit(e, monkeypatch)
    before = e.repo.head
    (e.repo.path / 'app.txt').write_text('external edit after interruption\n')
    with pytest.raises((Conflict, FrameworkError)):
        e.recover_candidate()
    assert e.repo.head == before
    assert (e.repo.path / 'app.txt').read_text() == 'external edit after interruption\n'
    assert list(e.store.root.glob('candidate-intent-*.json'))


def test_other_work_item_intent_does_not_hijack_automation_recovery(workflow):
    e, _ = implementing(workflow)
    path = e.store.root / ('candidate-intent-' + '0' * 40 + '.json')
    write_json(path, {'work': 'WORK-UNRELATED', 'package': e.work['package']})
    assert Automation(e, CONFIG).run()['state'] == 'ACCEPTED'
    assert path.exists()  # Never delete another work item's recovery record.
