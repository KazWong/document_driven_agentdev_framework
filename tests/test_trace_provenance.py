import pytest
from conftest import blueprint, plan
from agent_framework.common import FrameworkError
from agent_framework.scm import validate_trace
from agent_framework.policy import approval_count, needs_safety
from agent_framework.contracts import validate


def test_trace_accepts_union_of_cited_tasks_not_intersection():
    p = plan()
    p['tasks'].append({**p['tasks'][0], 'id': 'TASK-002', 'requirements': ['REQ-002'], 'design': ['CMP-002']})
    ref = {'id': 'PACKAGE-001', 'revision': 1, 'digest': 'f' * 64}
    trace = {'role': 'coder', 'artifact_type': 'implementation_trace', 'candidate_sha': 'a' * 40,
             'package_ref': ref, 'incomplete_obligations': [], 'changes': [{
                 'path': 'app.txt', 'requirement_ids': ['REQ-001', 'REQ-002'],
                 'design_ids': ['CMP-001', 'CMP-002'], 'task_ids': ['TASK-001', 'TASK-002']}]}
    class Repo:
        def diff(self, *args): return ['app.txt']
    validate_trace(Repo(), 'b' * 40, 'a' * 40, trace, blueprint(), p, ref)
    trace['changes'][0]['requirement_ids'].append('REQ-UNAUTHORIZED')
    with pytest.raises(FrameworkError, match='contradicts'):
        validate_trace(Repo(), 'b' * 40, 'a' * 40, trace, blueprint(), p, ref)

@pytest.mark.parametrize('risk', ['R0', 'R1', 'R2', 'R3'])
def test_one_approver_every_risk_with_safety_review_preserved(risk):
    assert approval_count(risk) == 1
    assert needs_safety(risk) == (risk in {'R2', 'R3'})

def test_review_notes_have_a_separate_schema_field():
    validate('ReviewerVerdict', {'role': 'reviewer', 'artifact_type': 'review',
        'candidate_sha': 'a' * 40, 'package_ref': {'id': 'PACKAGE-001', 'revision': 1, 'digest': 'f' * 64},
        'verdict': 'approved', 'findings': [], 'notes': ['Earlier ownership concern resolved by provenance.']})
