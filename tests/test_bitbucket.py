import pytest

from robotics_agent_env.bitbucket import infer_repository
from robotics_agent_env.util import AgentEnvError


@pytest.mark.parametrize("remote", [
    "git@bitbucket.org:team/repo.git",
    "ssh://git@bitbucket.org/team/repo.git",
    "https://bitbucket.org/team/repo.git",
    "https://user@bitbucket.org/team/repo",
])
def test_infer_repository(remote: str) -> None:
    assert infer_repository(remote) == ("team", "repo")


def test_rejects_non_bitbucket_remote() -> None:
    with pytest.raises(AgentEnvError):
        infer_repository("https://example.com/team/repo.git")
