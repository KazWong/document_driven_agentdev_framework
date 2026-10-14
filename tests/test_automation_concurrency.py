"""Real controller and locks; simulated backend, not live acceptance."""
import threading
from concurrent.futures import ThreadPoolExecutor
import pytest
from agent_framework.automation import Automation
from agent_framework.common import Conflict, read_json, write_json, locked
from agent_framework.execution import ExecutionResult, ProcessResult
from conftest import IsolatedBackendDouble, blueprint, plan

CONFIG = {'generation': 'ENV-001', 'role_action': 'role', 'selections': {'ENVREQ-001': 'ENV-001'}, 'verify_actions': {'ENVREQ-001': 'verify'}}

class ParallelBackend(IsolatedBackendDouble):
    def __init__(self):
        super().__init__()
        self.barrier = threading.Barrier(2, timeout=5)
        self.overlap = []
    def execute(self, request):
        data = read_json(request.read_only['/context'] / 'input.json')
        if (data.get('role') in {'coder', 'tester'} and data['context']['state'] == 'PROVIDER_FEASIBLE' and 'test_design_ref' not in data['context']):
            self.overlap.append(data['role'])
            self.barrier.wait()
            if data['role'] == 'coder':
                write_json(request.output / 'role-output.json', {
                    'schema_version': 1, 'role': 'coder', 'input_digest': data['input_digest'],
                    'output': {'role': 'coder', 'artifact_type': 'implementation_feasibility',
                               'package_ref': data['context']['package_ref'], 'handoff_ref': data['context']['handoff_ref'],
                               'feasible': True, 'findings': []}})
                return ExecutionResult(self.name, 'simulated-assessment', request.image, ProcessResult(0, 'simulated', ''), True)
        return super().execute(request)

def test_automatic_lifecycle_parallel_then_human_gates(workflow):
    e, _, _ = workflow
    backend = ParallelBackend()
    e.environments.backends[backend.name] = backend
    auto = Automation(e, CONFIG)
    assert auto.run()['state'] == 'APPROVAL_READY'
    assert sorted(backend.overlap) == ['coder', 'tester']
    assert e.work['approvals'] == []
    e.approve('one-human', e.work['package']['digest'])
    assert auto.run()['state'] == 'ACCEPTED'
    e.approve('one-human', e.work['acceptance']['digest'], release=True)
    assert auto.run()['state'] == 'CLOSED'
    assert e.store.check_integrity()['records'] > 0

def test_prepared_role_rejects_replanned_inputs(workflow):
    e, _, _ = workflow
    e.provider_preflight(CONFIG['selections'])
    run = e._prepare_role('tester', 'ENV-001', 'role')
    e.propose(blueprint(), plan(), ['ordinary_software'])
    with pytest.raises(Conflict): run()

def test_coder_cannot_implement_before_test_handoff(workflow):
    e, _, _ = workflow
    e.provider_preflight(CONFIG['selections'])
    with pytest.raises(Exception, match='read-only role modified'):
        e.run_role('coder', 'ENV-001', 'role')
    assert (e.repo.path / 'app.txt').read_text() == 'original\n'

def test_status_lock_available_during_execution(workflow):
    e, backend, _ = workflow
    e.provider_preflight(CONFIG['selections'])
    entered, release = threading.Event(), threading.Event()
    original = backend.execute
    def execute(request):
        entered.set()
        assert release.wait(5)
        return original(request)
    backend.execute = execute
    with ThreadPoolExecutor() as pool:
        pending = pool.submit(Automation(e, CONFIG)._role, 'tester')
        assert entered.wait(5)
        with locked(e.lockfile): assert e.work['state'] == 'PROVIDER_FEASIBLE'
        release.set()
        assert pending.result()['id'].startswith('JOB-')

def test_resume_does_not_repeat_completed_verification_cells(workflow):
    from conftest import make_candidate
    e, backend, suite = workflow
    make_candidate(e, suite)
    e.verify('ENVREQ-001', 'verify')
    n = sum(r.argv == ['test'] for r in backend.requests)
    assert Automation(e, CONFIG).run()['state'] == 'ACCEPTED'
    assert sum(r.argv == ['test'] for r in backend.requests) == n + 1  # final acceptance only

def test_reviewer_receives_separate_tester_provenance(workflow):
    from conftest import make_candidate
    e, backend, suite = workflow
    make_candidate(e, suite)
    e.verify('ENVREQ-001', 'verify')
    e.verified(e.run_role('tester', 'ENV-001', 'role'))
    execute = backend.execute
    observed = {}
    def capture(request):
        observed.update(read_json(request.read_only['/context'] / 'input.json')['context'])
        return execute(request)
    backend.execute = capture
    e.review(e.run_role('reviewer', 'ENV-001', 'role'))
    assert all(not c['path'].startswith('tests/') for c in observed['implementation_trace']['changes'])
    assert any(c['path'].startswith('tests/') for c in observed['candidate_trace']['changes'])
    assert observed['test_provenance']['author'] == 'tester'
    assert observed['test_provenance']['materializer'] == 'framework'
    assert 'unresolved defects only' in observed['review_output_contract']

def test_scm_workflow_waits_for_one_remote_human_then_closes(workflow, monkeypatch):
    import agent_framework.remote as remote
    e, _, _ = workflow
    p = plan()
    p.update(delivery='scm', scm={'provider': 'bitbucket', 'repository': 'owner/repo',
        'base_branch': 'main', 'required_checks': ['tests'], 'human_reviewers': ['human']})
    e.propose(blueprint(), p, ['ordinary_software'])
    backend = ParallelBackend()
    e.environments.backends[backend.name] = backend
    class Delivery:
        approved = False
        published = 0
        def publish(self, candidate, base, title, body):
            self.published += 1
            self.sha = candidate
            return {'number': 1, 'url': 'https://example.invalid/pr/1', 'baseRefName': base,
                    'headRefName': e.repo.branch(), 'headRefOid': candidate}
        def ci(self, pr, candidate, required):
            assert candidate == self.sha
            return {'candidate_sha': candidate, 'required': required}
        def review(self, pr, candidate):
            if not self.approved: raise Conflict('Awaiting human review')
            return {'actor': 'human', 'candidate_sha': candidate, 'review_id': 1}
        def promote(self, pr, candidate, required):
            assert self.approved and candidate == self.sha
            return {'candidate_sha': candidate, 'method': 'simulated'}
    d = Delivery()
    monkeypatch.setattr(remote, 'delivery_for', lambda *args: d)
    auto = Automation(e, {**CONFIG, 'authorize_remote': True})
    assert auto.run()['state'] == 'APPROVAL_READY'
    e.approve('human', e.work['package']['digest'])
    assert auto.run()['state'] == 'CI_VERIFIED'
    assert not e.work['release_approvals']
    assert auto.run()['state'] == 'CI_VERIFIED'
    assert d.published == 1
    d.approved = True
    assert auto.run()['state'] == 'CLOSED'
    assert len(e.work['release_approvals']) == 1

def test_replan_reuses_clean_controller_checkout_after_new_approval(workflow):
    from conftest import make_candidate, preflight
    e, _, suite = workflow
    make_candidate(e, suite)
    old_head, original_base = e.repo.head, e.work['base_sha']
    e.propose(blueprint(), plan(), ['ordinary_software'])
    preflight(e, suite)
    e.approve('one-human', e.work['package']['digest'])
    e.start()
    assert e.repo.head == old_head
    assert e.work['base_sha'] == original_base
    assert e.work['prior_implementation_trace']

def test_automatic_coder_repair_uses_failure_context_and_budget(workflow):
    from conftest import preflight
    e, _, suite = workflow
    preflight(e, suite)
    e.approve('human', e.work['package']['digest'])
    class RepairBackend(IsolatedBackendDouble):
        def __init__(self):
            super().__init__()
            self.codes = 0
        def execute(self, request):
            data = read_json(request.read_only['/context'] / 'input.json')
            if request.argv == ['test']:
                self.status = 'candidate_failed' if self.codes == 1 else 'passed'
            result = super().execute(request)
            if data.get('role') == 'coder' and data['context']['state'] == 'IMPLEMENTING':
                self.codes += 1
                if self.codes == 2:
                    assert data['context']['repair_failure']['class'] == 'candidate_failed'
                    (request.project / 'app.txt').write_text('repaired by isolated coder\n')
            return result
    backend = RepairBackend()
    e.environments.backends[backend.name] = backend
    assert Automation(e, CONFIG).run()['state'] == 'ACCEPTED'
    assert backend.codes == 2
    assert e.work['automatic_repairs'] == 1
    assert (e.repo.path / 'app.txt').read_text() == 'repaired by isolated coder\n'
