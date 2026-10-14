import copy
import json
import pytest
from agent_framework.common import Conflict, FrameworkError
from agent_framework.remote import GitHubDelivery, BitbucketDelivery, BitbucketAPI, delivery_for

SHA = 'a' * 40
PR = {'number': 7, 'url': 'https://example.invalid/pr/7', 'headRefName': 'agent/work-001', 'baseRefName': 'main'}

class GitHub(GitHubDelivery):
    def __init__(self):
        self.reviewers = ['human']
        self.repository = 'owner/repo'
        self.value = {**PR, 'headRefOid': SHA, 'state': 'OPEN', 'author': {'login': 'bot'}}
        self.reviews = [{'id': 1, 'user': {'login': 'human', 'type': 'User'}, 'state': 'APPROVED', 'commit_id': SHA}]
    def _gh(self, *args):
        return json.dumps([self.reviews] if args[0] == 'api' else self.value)

class API:
    def __init__(self):
        self.value = {'id': 7, 'state': 'OPEN', 'author': {'uuid': 'bot'},
            'source': {'commit': {'hash': SHA}, 'branch': {'name': 'agent/work-001'}, 'repository': {'full_name': 'owner/repo'}},
            'destination': {'branch': {'name': 'main'}, 'repository': {'full_name': 'owner/repo'}},
            'participants': [{'approved': True, 'user': {'uuid': 'human', 'type': 'user'}}]}
        self.comments = [{'id': 2, 'user': {'uuid': 'human'}, 'content': {'raw': 'APPROVE ' + SHA}}]
        self.checks = [{'key': 'tests', 'state': 'SUCCESSFUL'}]
    def call(self, method, path, body=None): return copy.deepcopy(self.value)
    def pages(self, path): return copy.deepcopy(self.comments if '/comments' in path else self.checks)

@pytest.mark.parametrize('defect', ['sha', 'bot', 'dismissed', 'change_request', 'unlisted', 'author', 'closed'])
def test_github_rejects_invalid_human_approval(defect):
    d = GitHub()
    if defect == 'sha': d.reviews[0]['commit_id'] = 'b' * 40
    if defect == 'bot': d.reviews[0]['user']['type'] = 'Bot'
    if defect == 'dismissed': d.reviews.append({**d.reviews[0], 'id': 2, 'state': 'DISMISSED'})
    if defect == 'change_request': d.reviews.append({**d.reviews[0], 'id': 2, 'state': 'CHANGES_REQUESTED'})
    if defect == 'unlisted': d.reviewers = ['someone-else']
    if defect == 'author': d.value['author']['login'] = 'human'
    if defect == 'closed': d.value['state'] = 'CLOSED'
    with pytest.raises(Conflict): d.review(PR, SHA)

def test_one_github_review_of_exact_commit():
    assert GitHub().review(PR, SHA)['actor'] == 'human'

@pytest.mark.parametrize('defect', ['sha', 'base', 'repo', 'closed', 'unapproved', 'missing_sha_comment', 'changes', 'ci'])
def test_bitbucket_rejects_invalid_evidence(defect):
    api = API()
    d = BitbucketDelivery(None, 'owner/repo', api)
    d.reviewers = ['human']
    if defect == 'sha': api.value['source']['commit']['hash'] = 'b' * 40
    if defect == 'base': api.value['destination']['branch']['name'] = 'other'
    if defect == 'repo': api.value['source']['repository']['full_name'] = 'other/repo'
    if defect == 'closed': api.value['state'] = 'MERGED'
    if defect == 'unapproved': api.value['participants'][0]['approved'] = False
    if defect == 'missing_sha_comment': api.comments = []
    if defect == 'changes': api.value['participants'].append({'state': 'changes_requested'})
    if defect == 'ci': api.checks[0]['state'] = 'FAILED'
    with pytest.raises(Conflict):
        if defect == 'ci': d.ci(PR, SHA, ['tests'])
        else: d.review(PR, SHA)

def test_bitbucket_approval_and_commit_ci():
    d = BitbucketDelivery(None, 'owner/repo', API())
    d.reviewers = ['human']
    assert d.review(PR, SHA)['candidate_sha'] == SHA
    assert d.ci(PR, SHA, ['tests'])['provider'] == 'bitbucket'

def test_bitbucket_pagination_cycles_fail():
    api = object.__new__(BitbucketAPI)
    api.call = lambda *args: {'values': [], 'next': 'same'}
    with pytest.raises(FrameworkError, match='pagination'): api.pages('same')

def test_wrong_git_push_destination_rejected():
    class Repo:
        def git(self, *args):
            return 'git@github.com:other/repo.git' if '--push' in args else 'git@github.com:owner/repo.git'
    with pytest.raises(Conflict, match='origin'):
        delivery_for(Repo(), {'provider': 'github', 'repository': 'owner/repo', 'human_reviewers': ['human']})
