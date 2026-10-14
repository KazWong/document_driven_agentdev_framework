"""Fault-injection regressions for the uploaded v2.1.0/work005 candidate.

Backends here are explicit contract doubles, not Docker/ROS/live acceptance.
"""
import copy
import importlib.util
import json
from pathlib import Path

import pytest

from agent_framework.automation import Automation
from agent_framework.common import FrameworkError, read_json, write_json
from agent_framework.contracts import validate_blueprint, validate_plan
from agent_framework.engine import Engine
from agent_framework.scm import Repository
from agent_framework.store import Store
from conftest import blueprint, plan, preflight, changes
from test_automation_concurrency import CONFIG, ParallelBackend


def fresh_engine(workflow, tmp_path):
    parent, _, _ = workflow
    return Engine(Repository(parent.repo.path), Store(tmp_path / 'fresh-state'),
                  parent.environments, 'WORK-REPAIR')


class PlanningBackend(ParallelBackend):
    def __init__(self, invalid=1, *, malformed=False, absolute=True):
        super().__init__()
        self.invalid = invalid
        self.malformed = malformed
        self.absolute = absolute
        self.plans = []

    def execute(self, request):
        data = read_json(request.read_only['/context'] / 'input.json')
        result = super().execute(request)
        if data.get('role') == 'planner' and data['context']['state'] == 'INTAKE':
            self.plans.append(data)
            if len(self.plans) <= self.invalid:
                value = read_json(request.output / 'role-output.json')
                if self.malformed:
                    value['output']['plan']['risk_class'] = 'INVALID'
                elif self.absolute:
                    value['output']['plan']['scope']['include'][1] = '/tests/**'
                else:
                    value['output']['plan']['tasks'][0]['requirements'] = ['REQ-UNKNOWN']
                write_json(request.output / 'role-output.json', value)
        return result


@pytest.mark.parametrize('malformed', [False, True])
def test_invalid_planner_output_is_preserved_and_freshly_retried(workflow, tmp_path, malformed):
    e = fresh_engine(workflow, tmp_path)
    backend = PlanningBackend(malformed=malformed)
    e.environments.backends[backend.name] = backend
    try:
        e.new('Implement a message tool')
        assert Automation(e, CONFIG).run()['state'] == 'APPROVAL_READY'
        assert len(backend.plans) == 2
        assert e.work['automatic_replans'] == 1
        failure = e.store.resolve(e.work['failures'][0])['payload']
        assert failure['owner'] == 'planner'
        assert failure.get('result')
        assert backend.plans[1]['context']['prior_failure']['findings']
        assert backend.plans[0]['input_digest'] != backend.plans[1]['input_digest']
        assert e.work['approvals'] == []
        assert e.store.check_integrity()['records'] > 0
    finally:
        e.store.close()


def test_rejected_planning_retry_budget_survives_scheduler_restart(workflow, tmp_path):
    e = fresh_engine(workflow, tmp_path)
    backend = PlanningBackend(invalid=100)
    e.environments.backends[backend.name] = backend
    try:
        e.new('Implement a message tool')
        cfg = {**CONFIG, 'repair_budget': 2}
        result = Automation(e, cfg).run()
        assert result['state'] == 'REPLAN_REQUIRED'
        assert 'budget' in result['reason'].lower()
        assert len(backend.plans) == 3
        assert e.work['automatic_replans'] == 2
        assert Automation(e, cfg).run()['state'] == 'REPLAN_REQUIRED'
        assert len(backend.plans) == 3
    finally:
        e.store.close()


def test_feasibility_replan_does_not_crash_coder_after_new_approval(workflow):
    e, backend, sref = workflow
    e.provider_preflight(CONFIG['selections'])
    backend.mutate_output = lambda r: r['output'].update(feasible=False, findings=['REQ-001 needs clarification'])
    e.tester_preflight(sref, e.run_role('tester', 'ENV-001', 'role', suite_ref=sref))
    backend.mutate_output = None
    e.import_planning(e.run_role('planner', 'ENV-001', 'role'))
    parallel = ParallelBackend()
    e.environments.backends[parallel.name] = parallel
    assert Automation(e, CONFIG).run()['state'] == 'APPROVAL_READY'
    e.approve('human', e.work['package']['digest'])
    assert Automation(e, CONFIG).run()['state'] == 'ACCEPTED'


@pytest.mark.parametrize('value', ['false', 'true', 1, [], {}])
def test_remote_authorization_must_be_an_actual_boolean(workflow, value):
    with pytest.raises(FrameworkError, match='authorize_remote'):
        Automation(workflow[0], {**CONFIG, 'authorize_remote': value})


@pytest.mark.parametrize('field,value', [('selections', []), ('verify_actions', []),
                                        ('generation', None), ('role_action', ''),
                                        ('actor', 123)])
def test_automation_config_fails_with_actionable_contract_errors(workflow, field, value):
    with pytest.raises(FrameworkError):
        Automation(workflow[0], {**CONFIG, field: value})


def test_plan_task_cannot_advertise_paths_outside_scope():
    p = plan()
    p['tasks'][0]['paths'].append('unauthorized/**')
    with pytest.raises(FrameworkError, match='scope'):
        validate_plan(p, blueprint())


def test_final_acceptance_preserves_documented_small_subset_contract():
    bp = blueprint()
    bp['verification_obligations'].append({'id': 'VER-002', 'text': 'Another required check', 'required': True})
    bp['traceability'][0]['verifications'].append('VER-002')
    # docs/design/final-acceptance-suite.md explicitly selects a small subset;
    # targeted verification still covers all mandatory obligations.
    validate_blueprint(bp)


@pytest.mark.parametrize('incomplete', [False, True])
def test_invalid_coder_trace_cannot_dirty_controller_checkout(workflow, incomplete):
    e, backend, sref = workflow
    preflight(e, sref)
    e.approve('human', e.work['package']['digest'])
    e.start()
    if incomplete:
        backend.mutate_output = lambda r: r['output'].update(incomplete_obligations=['VER-001'])
    else:
        backend.mutate_output = lambda r: r['output']['changes'][0].update(task_ids=['TASK-UNKNOWN'])
    before = e.repo.head
    with pytest.raises(FrameworkError):
        e.run_role('coder', 'ENV-001', 'role')
    assert e.repo.clean()
    assert e.repo.head == before
    assert (e.repo.path / 'app.txt').read_text() == 'original\n'


def load_driver():
    path = Path(__file__).parents[1] / 'providers/codex/driver.py'
    spec = importlib.util.spec_from_file_location('repair_codex_driver', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize('payload', ['{"role":"planner","role":"coder"}',
                                   '{"nested":{"a":1,"a":2}}', '{"a":NaN}', '{"a":Infinity}'])
def test_codex_transport_does_not_normalize_invalid_json(payload):
    with pytest.raises(ValueError):
        load_driver().decode_transport({'payload': payload})
