"""Resumable controller orchestration. Human approvals are never synthesized."""
from concurrent.futures import ThreadPoolExecutor

from .common import Conflict, FrameworkError, digest, locked
from .engine import Engine
from .environments import Environments
from .policy import needs_safety
from .scm import Repository
from .store import Store
from .test_artifacts import development_hashes


class Automation:
    def __init__(self, engine, config):
        self.engine, self.config = engine, config
        for key in ('generation', 'role_action', 'selections', 'verify_actions'):
            if key not in config:
                raise FrameworkError('automation config missing ' + key)
        self.budget = config.get('repair_budget', 2)
        if type(self.budget) is not int or not 0 <= self.budget <= 10:
            raise FrameworkError('repair_budget must be between 0 and 10')

    def _role(self, name, suite=None):
        # Each concurrent worker owns its SQLite connections and Engine.
        parent = self.engine
        with Store(parent.store.root) as store:
            envs = Environments(parent.environments.store.root, parent.environments.backends)
            try:
                engine = Engine(Repository(parent.repo.path), store, envs, parent.work_id)
                work = engine.work
                key = engine.work_id + '-AUTO-' + digest({
                    'role': name, 'state': work['state'], 'suite': suite,
                    'draft': work.get('draft'), 'package': work.get('package'),
                    'candidate': work.get('candidate'), 'head': engine.repo.head,
                    'failures': work.get('failures'),
                    'generation': self.config['generation'], 'action': self.config['role_action'],
                })[:24].upper()
                if store.exists(key):
                    receipt = store.get(key)['payload']
                    store.resolve(receipt['job'], current=True)
                    return receipt['job']
                job = engine.run_role(name, self.config['generation'], self.config['role_action'], suite_ref=suite)
                store.publish(key, 'automation_receipt', 'framework', {'job': job}, [(job['id'], 'derived_from')])
                return job
            finally:
                envs.store.close()

    def _pause(self, reason):
        work = self.engine.work
        return {'state': work['state'], 'status': 'waiting', 'reason': reason,
                'package': work.get('package'), 'acceptance': work.get('acceptance'),
                'pull_request': work.get('pull_request')}

    def watch(self, *, timeout=3600, poll_seconds=15):
        import time
        if not 1 <= poll_seconds <= 60 or not 1 <= timeout <= 86400:
            raise FrameworkError('watch bounds: poll 1..60 seconds; timeout 1..86400 seconds')
        deadline = time.monotonic() + timeout
        while True:
            result = self.run()
            if result['status'] == 'completed' or result['state'] in {'BLOCKED', 'REPLAN_REQUIRED'}:
                return result
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return {**result, 'watch': 'timeout; rerun resumes recorded progress'}
            time.sleep(min(poll_seconds, remaining))

    def run(self):
        e = self.engine
        # A scheduler lock prevents duplicate dispatch without serializing its workers.
        with locked(e.store.root / ('automation-' + e.work_id + '.lock')):
            for _ in range(100):
                w = e.work
                state = w['state']
                if state == 'INTAKE':
                    e.import_planning(self._role('planner'))
                elif state == 'DRAFT':
                    e.provider_preflight(self.config['selections'])
                elif state == 'PROVIDER_FEASIBLE':
                    with ThreadPoolExecutor(max_workers=2) as pool:
                        tester = pool.submit(self._role, 'tester')
                        coder = pool.submit(self._role, 'coder')
                        test_job, code_job = tester.result(), coder.result()
                    assessment = e._role_output(code_job, 'coder', [w['draft'], w['provider_feasibility']])
                    if not assessment['feasible']:
                        with locked(e.lockfile), e.store.transaction():
                            e._replan(e.work, code_job, assessment['findings'])
                        continue
                    # Successful preliminary Coder review cannot replace test handoff.
                    suite = e.import_test_design(test_job)
                    e.tester_preflight(suite, self._role('tester', suite))
                elif state == 'TESTER_FEASIBLE':
                    e.coder_preflight(self._role('coder'))
                elif state == 'FEASIBLE':
                    e.reconcile(self._role('planner'))
                elif state == 'APPROVAL_READY':
                    return self._pause('One human must approve the current engineering package digest.')
                elif state == 'APPROVED':
                    e.start()
                elif state == 'IMPLEMENTING':
                    if list(e.store.root.glob('candidate-intent-*.json')):
                        e.recover_candidate()
                        continue
                    job = self._role('coder')
                    output = e._current(job)['output']
                    if output['incomplete_obligations']:
                        raise Conflict('Coder reports incomplete obligations')
                    changes = {c['path']: c for c in output['changes']}
                    if w.get('candidate') or w.get('prior_implementation_trace'):
                        prior = (e.store.resolve(w['candidate'])['payload']['trace']['changes'] if w.get('candidate') else w['prior_implementation_trace'])
                        protected = set(development_hashes(e.store, w['suite']))
                        for c in prior:
                            if c['path'] not in protected:
                                changes.setdefault(c['path'], c)
                    # Candidate creation validates the complete cumulative Git diff.
                    e.candidate(list(changes.values()))
                elif state in {'CANDIDATE', 'ACCEPTING'}:
                    final = state == 'ACCEPTING'
                    requirements = (e._current(w['blueprint'])['final_acceptance']['required_environments'] if final else w['bindings'])
                    for requirement in sorted(requirements):
                        try:
                            done = e._matrix(e.work, final, only_environment=requirement)
                        except Conflict:
                            done = []
                        if done:
                            continue
                        action = self.config['verify_actions'].get(requirement)
                        if not action:
                            raise FrameworkError('No verification action configured for ' + requirement)
                        e.verify(requirement, action, final=final)
                        if e.work['state'] != state:
                            break
                    if e.work['state'] == state:
                        if final:
                            e.accept()
                        else:
                            e.verified(self._role('tester'))
                elif state == 'VERIFIED':
                    roles = ['reviewer'] + (['safety_reviewer'] if needs_safety(e._current(w['plan'])['risk_class']) else [])
                    for role in roles:
                        if role not in e.work['reviews']:
                            e.review(self._role(role))
                        if e.work['state'] != 'VERIFIED':
                            break
                elif state == 'REVIEWED':
                    e.accepting()
                elif state == 'ACCEPTED':
                    plan = e._current(w['plan'])
                    if plan['delivery'] != 'scm':
                        return self._pause('One human must approve artifact release.')
                    if not self.config.get('authorize_remote'):
                        return self._pause('Set authorize_remote to publish the accepted branch and PR.')
                    e.publish_pull_request(self.config.get('actor', 'automation'),
                                           self.config.get('title', 'Implement ' + e.work_id),
                                           'Automated candidate ' + e._current(w['candidate'])['sha'] +
                                           '\nAcceptance: ' + w['acceptance']['digest'])
                elif state == 'PR_OPEN':
                    try:
                        e.record_ci()
                    except Conflict as exc:
                        return self._pause(str(exc))
                elif state == 'CI_VERIFIED':
                    try:
                        e.sync_remote_review()
                    except Conflict as exc:
                        return self._pause(str(exc))
                elif state == 'RELEASE_APPROVED':
                    e.promote(remote_authorized=self.config.get('authorize_remote', False))
                elif state == 'PROMOTED':
                    e.close()
                elif state == 'CLOSED':
                    return {'state': state, 'status': 'completed', 'promotion': w['promotion']}
                elif state == 'DIAGNOSING':
                    e.diagnose(self._role('debugger'))
                elif state == 'BLOCKED':
                    failure = e._current(w['failures'][-1])
                    count = w.get('automatic_repairs', 0)
                    owner = failure['owner']
                    if w.get('diagnosis'):
                        diagnosis = e._current(w['diagnosis'])['output']
                        if diagnosis['failure_ref'] == w['failures'][-1]:
                            owner = diagnosis['owner']
                    if owner != 'coder' or count >= self.budget:
                        return self._pause('Failure requires ' + owner + '; automatic repair budget remaining: ' + str(max(0, self.budget-count)))
                    e.resume('automation-policy', repair_source=True, automatic_budget=self.budget)
                elif state == 'REPLAN_REQUIRED':
                    if w.get('automatic_replans', 0) >= self.budget:
                        return self._pause('Planner revision budget exhausted.')
                    count = w.get('automatic_replans', 0)
                    e.import_planning(self._role('planner'))
                    with locked(e.lockfile), e.store.transaction():
                        current = e.work
                        current['automatic_replans'] = count + 1
                        e._save(current)
                else:
                    raise Conflict('Unsupported automation state ' + state)
            raise Conflict('Automation step budget exhausted; inspect state before continuing')
