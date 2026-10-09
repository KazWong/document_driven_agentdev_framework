from agent_framework.common import Conflict
from agent_framework.remote import GitHubDelivery
from agent_framework.execution import ProcessResult
import json
import pytest


class Executor:
    def __init__(self, value):
        self.value = value

    def run(self, *args, **kwargs):
        return ProcessResult(0, json.dumps(self.value), "")


def test_ci_requires_exact_head_and_every_named_check(workflow):
    e, _, _ = workflow
    head = e.repo.head
    value = {
        "headRefOid": head,
        "baseRefName": "main",
        "state": "OPEN",
        "statusCheckRollup": [
            {"name": "required", "conclusion": "SUCCESS", "status": "COMPLETED"}
        ],
    }
    delivery = GitHubDelivery(e.repo, Executor(value))
    pr = {"number": 1, "baseRefName": "main"}
    assert delivery.ci(pr, head, ["required"])["candidate_sha"] == head
    with pytest.raises(Conflict):
        delivery.ci(pr, "f" * 40, ["required"])
    with pytest.raises(Conflict):
        delivery.ci(pr, head, ["missing"])
    value["statusCheckRollup"].append(value["statusCheckRollup"][0].copy())
    with pytest.raises(Conflict):
        delivery.ci(pr, head, ["required"])
