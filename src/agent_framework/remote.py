"""Controller-only GitHub and Bitbucket Cloud delivery and human review."""

from __future__ import annotations

from pathlib import Path
import re
import tempfile
from typing import Any

from .common import Conflict, FrameworkError, decode, sha
from .execution import ProcessExecutor
from .scm import Repository


class GitHubDelivery:
    def __init__(self, repo: Repository, executor: ProcessExecutor | None = None):
        self.repo = repo
        self.executor = executor or ProcessExecutor()
        self.reviewers = []

    def _gh(self, *argv: str) -> Any:
        import os
        env = {k: os.environ[k] for k in ("GH_TOKEN", "GITHUB_TOKEN", "GH_CONFIG_DIR") if k in os.environ}
        if getattr(self, "repository", None):
            env["GH_REPO"] = self.repository
        result = self.executor.run(["gh", *argv], cwd=self.repo.path, timeout=120, env=env)
        if result.returncode or result.timed_out or result.output_limited:
            raise FrameworkError("GitHub operation failed: " + result.stderr[:500])
        return result.stdout

    def head(self, branch: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_./-]*", branch) or ".." in branch:
            raise FrameworkError("invalid remote branch name")
        value = self.repo.git("ls-remote", "--heads", "origin", "refs/heads/" + branch)
        rows = value.strip().splitlines()
        if len(rows) != 1:
            raise Conflict("remote branch head is unavailable or ambiguous")
        return sha(rows[0].split()[0])

    def _push(self, candidate, base):
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_./-]*', base) or '..' in base:
            raise FrameworkError('invalid base branch')
        if base == self.repo.branch():
            raise Conflict('feature and base branches must differ')
        if (
            self.repo.head != candidate
            or not self.repo.clean()
            or not self.repo.branch().startswith("agent/")
        ):
            raise Conflict(
                "pull request must publish the exact clean feature-branch candidate"
            )
        # No force, implicit add, commit, merge, rebase or branch reset.
        self.repo.git(
            "push",
            "origin",
            candidate + ":refs/heads/" + self.repo.branch(),
            timeout=120,
        )
        if self.head(self.repo.branch()) != candidate:
            raise Conflict("remote feature branch changed during publication")
    def review(self, pr, candidate):
        value = decode(self._gh('pr', 'view', str(pr['number']), '--json',
                                'headRefOid,headRefName,baseRefName,state,author'))
        if (value['headRefOid'] != candidate or value['state'] != 'OPEN'
                or value['baseRefName'] != pr['baseRefName']
                or value['headRefName'] != pr['headRefName']):
            raise Conflict('remote review belongs to a different head/base/state')
        pages = decode(self._gh('api', 'repos/' + self.repository + '/pulls/' + str(pr['number']) + '/reviews',
                                '--paginate', '--slurp'))
        latest = {}
        for r in sorted([r for page in pages for r in page], key=lambda r: r['id']):
            who = r['user']['login']
            if r.get('state') in {'APPROVED', 'CHANGES_REQUESTED', 'DISMISSED'}:
                latest[who] = r
        if any(r['state'] == 'CHANGES_REQUESTED' for r in latest.values()):
            raise Conflict('GitHub has unresolved change requests')
        for who, r in latest.items():
            if (who in self.reviewers and who != value['author']['login']
                    and r['user']['type'] == 'User' and r['state'] == 'APPROVED'
                    and r['commit_id'] == candidate):
                # A second observation detects branch movement during review pagination.
                current = decode(self._gh('pr', 'view', str(pr['number']), '--json',
                                          'headRefOid,baseRefName,state'))
                if (current['headRefOid'] != candidate or current['state'] != 'OPEN'
                        or current['baseRefName'] != pr['baseRefName']):
                    raise Conflict('GitHub PR changed during review retrieval')
                return {'actor': who, 'candidate_sha': candidate,
                        'review_id': r['id'], 'provider': 'github', 'url': pr['url']}
        raise Conflict('Awaiting an authorized human review of the current GitHub commit')

    def publish(
        self, candidate: str, base: str, title: str, body: str
    ) -> dict[str, Any]:
        self._push(candidate, base)
        existing = decode(self._gh('pr', 'list', '--state', 'open', '--head', self.repo.branch(),
                                   '--base', base, '--json', 'number,url,headRefOid,headRefName,baseRefName'))
        if len(existing) > 1:
            raise Conflict('multiple matching GitHub pull requests')
        with tempfile.TemporaryDirectory(prefix="pr-body-") as tmp:
            path = Path(tmp) / "body.txt"
            path.write_text(body)
            if existing:
                self._gh('pr', 'edit', str(existing[0]['number']), '--title', title, '--body-file', str(path))
            else:
                self._gh('pr', 'create', '--base', base, '--head', self.repo.branch(),
                         '--title', title, '--body-file', str(path))
        value = decode(
            self._gh(
                "pr",
                "view",
                self.repo.branch(),
                "--json",
                "number,url,headRefOid,headRefName,baseRefName",
            )
        )
        if value["headRefOid"] != candidate or value["baseRefName"] != base:
            raise Conflict(
                "created pull request differs from the approved candidate/base"
            )
        return value

    def ci(
        self, pr: dict[str, Any], candidate: str, required: list[str]
    ) -> dict[str, Any]:
        value = decode(
            self._gh(
                "pr",
                "view",
                str(pr["number"]),
                "--json",
                "headRefOid,baseRefName,statusCheckRollup,state",
            )
        )
        if (
            value["headRefOid"] != candidate
            or value["baseRefName"] != pr["baseRefName"]
            or value["state"] != "OPEN"
        ):
            raise Conflict("remote pull request moved or closed")
        checks = {}
        for check in value["statusCheckRollup"] or []:
            name = check.get("name", check.get("context"))
            passed = (
                check.get("conclusion") == "SUCCESS"
                and check.get("status") == "COMPLETED"
                or check.get("state") == "SUCCESS"
            )
            # Duplicate names are ambiguous rather than silently overwritten.
            if name in checks:
                raise Conflict("ambiguous duplicate CI check name")
            checks[name] = passed
        if not required or any(not checks.get(name, False) for name in required):
            raise Conflict("required exact-head CI checks have not passed")
        return {
            "candidate_sha": candidate,
            "required": required,
            "checks": value["statusCheckRollup"],
            "provider": "github",
        }

    def promote(
        self, pr: dict[str, Any], candidate: str, required: list[str]
    ) -> dict[str, Any]:
        self.ci(pr, candidate, required)
        self.review(pr, candidate)
        # A new merge result would have an untested tree. Fast-forward only to the
        # accepted SHA; server branch rules can refuse this, with no bypass.
        base = pr["baseRefName"]
        self.repo.git("push", "origin", candidate + ":refs/heads/" + base, timeout=120)
        if self.head(base) != candidate:
            raise Conflict(
                "remote changed after promotion; inspect remote state before retrying"
            )
        return {
            "candidate_sha": candidate,
            "base": base,
            "method": "verified_fast_forward",
            "remote_head": candidate,
        }


def delivery_for(repo, scm):
    """Bind API and Git operations to the same explicitly configured repository."""
    provider = scm.get('provider', 'github')
    repository = scm.get('repository')
    if not repository or not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository):
        raise FrameworkError('SCM requires provider and owner/repository configuration')
    host = {'github': 'github.com', 'bitbucket': 'bitbucket.org'}.get(provider)
    if host is None:
        raise FrameworkError('unsupported SCM provider')
    remote = repo.git('remote', 'get-url', 'origin').strip()
    allowed = {f'git@{host}:{repository}.git', f'https://{host}/{repository}.git',
               f'https://{host}/{repository}', f'ssh://git@{host}/{repository}.git'}
    push_remote = repo.git('remote', 'get-url', '--push', 'origin').strip()
    if remote not in allowed or push_remote not in allowed:
        raise Conflict('origin fetch/push URL differs from approved SCM repository')
    obj = GitHubDelivery(repo) if provider == 'github' else BitbucketDelivery(repo, repository)
    obj.repository = repository
    obj.reviewers = scm.get('human_reviewers', [])
    if not obj.reviewers:
        raise FrameworkError('SCM requires an explicit human_reviewers allowlist')
    return obj


class BitbucketAPI:
    """Bitbucket Cloud only. Credentials stay in the trusted controller process."""
    def __init__(self):
        import os
        import base64
        token = os.environ.get('BITBUCKET_TOKEN')
        email = os.environ.get('BITBUCKET_EMAIL')
        if not token:
            raise FrameworkError('BITBUCKET_TOKEN is required on the controller')
        self.authorization = ('Basic ' + base64.b64encode((email + ':' + token).encode()).decode()
                              if email else 'Bearer ' + token)

    def call(self, method, path, body=None):
        import json
        from urllib.request import Request, build_opener, HTTPRedirectHandler
        from urllib.error import HTTPError, URLError
        url = path if path.startswith('https://') else 'https://api.bitbucket.org/2.0/' + path
        if not url.startswith('https://api.bitbucket.org/2.0/repositories/'):
            raise FrameworkError('unexpected Bitbucket pagination URL')
        class NoRedirect(HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                raise FrameworkError('Bitbucket API redirect refused')
        request = Request(url, method=method, data=None if body is None else json.dumps(body).encode(),
                          headers={'Authorization': self.authorization, 'Accept': 'application/json',
                                   'Content-Type': 'application/json'})
        try:
            with build_opener(NoRedirect()).open(request, timeout=30) as response:
                data = response.read(4 * 1024 * 1024 + 1)
            if len(data) > 4 * 1024 * 1024:
                raise FrameworkError('Bitbucket response exceeded limit')
            return json.loads(data)
        except HTTPError as exc:
            raise FrameworkError('Bitbucket API failed with HTTP ' + str(exc.code)) from None
        except URLError:
            raise FrameworkError('Bitbucket API connection failed') from None

    def pages(self, path):
        result, seen = [], set()
        while path:
            if path in seen or len(seen) >= 100:
                raise FrameworkError('Bitbucket pagination cycle or limit exceeded')
            seen.add(path)
            page = self.call('GET', path)
            result.extend(page['values'])
            path = page.get('next')
        return result


class BitbucketDelivery(GitHubDelivery):
    def __init__(self, repo, repository, api=None):
        super().__init__(repo)
        self.repository = repository
        self.api = api or BitbucketAPI()
        self.root = 'repositories/' + repository
        self.reviewers = []

    def _view(self, pr, candidate):
        value = self.api.call('GET', self.root + '/pullrequests/' + str(pr['number']))
        if (value['state'] != 'OPEN' or value['source']['commit']['hash'] != candidate
                or value['destination']['branch']['name'] != pr['baseRefName']
                or value['source']['branch']['name'] != pr['headRefName']
                or value['source']['repository']['full_name'] != self.repository
                or value['destination']['repository']['full_name'] != self.repository):
            raise Conflict('Bitbucket PR head, repository, base or state changed')
        return value

    def publish(self, candidate, base, title, body):
        self._push(candidate, base)
        prs = [p for p in self.api.pages(self.root + '/pullrequests?state=OPEN&pagelen=100')
               if p['source']['branch']['name'] == self.repo.branch()
               and p['source']['repository']['full_name'] == self.repository
               and p['destination']['branch']['name'] == base]
        if len(prs) > 1:
            raise Conflict('multiple matching Bitbucket pull requests')
        payload = {'title': title, 'description': body, 'source': {'branch': {'name': self.repo.branch()}},
                   'destination': {'branch': {'name': base}}, 'close_source_branch': False}
        if prs:
            value = self.api.call('PUT', self.root + '/pullrequests/' + str(prs[0]['id']),
                                  {'title': title, 'description': body})
        else:
            value = self.api.call('POST', self.root + '/pullrequests', payload)
        pr = {'number': value['id'], 'url': value['links']['html']['href'],
              'headRefOid': candidate, 'headRefName': self.repo.branch(),
              'baseRefName': base, 'provider': 'bitbucket', 'repository': self.repository}
        self._view(pr, candidate)
        return pr

    def ci(self, pr, candidate, required):
        self._view(pr, candidate)
        checks = self.api.pages(self.root + '/commit/' + sha(candidate) + '/statuses?pagelen=100')
        values = {}
        for check in checks:
            key = check['key']
            if key in values:
                raise Conflict('ambiguous duplicate Bitbucket CI key')
            values[key] = check['state'] == 'SUCCESSFUL'
        if not required or any(not values.get(k) for k in required):
            raise Conflict('required Bitbucket commit checks have not passed')
        self._view(pr, candidate)
        return {'candidate_sha': candidate, 'required': required, 'checks': checks, 'provider': 'bitbucket'}

    def review(self, pr, candidate):
        value = self._view(pr, candidate)
        participants = value.get('participants', [])
        if any(p.get('state') == 'changes_requested' for p in participants):
            raise Conflict('Bitbucket has unresolved change requests')
        approved = {p['user']['uuid'] for p in participants if p.get('approved')
                    and p['user']['uuid'] in self.reviewers
                    and p['user'].get('type') == 'user'
                    and p['user']['uuid'] != value['author']['uuid']}
        # Cloud approvals do not expose a commit SHA. Require an explicit human SHA
        # attestation in the PR as well as the current approved participant state.
        comments = self.api.pages(self.root + '/pullrequests/' + str(pr['number']) + '/comments?pagelen=100')
        eligible = [c for c in comments if not c.get('deleted')
                    and c['user']['uuid'] in approved
                    and c.get('content', {}).get('raw', '').strip() == 'APPROVE ' + candidate]
        if not eligible:
            raise Conflict('Awaiting human approval and PR comment: APPROVE ' + candidate)
        self._view(pr, candidate)
        item = sorted(eligible, key=lambda x: x['id'])[-1]
        return {'actor': item['user']['uuid'], 'candidate_sha': candidate,
                'review_id': item['id'], 'provider': 'bitbucket', 'url': pr['url']}
