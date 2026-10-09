"""Exercise the actual provider runner with real pytest, outside Docker."""

import importlib.util
from pathlib import Path

import pytest

from agent_framework.common import read_json, write_json


@pytest.mark.parametrize(
    "source,expected,count",
    [
        ("def test_pass(): assert 2 + 2 == 4\n", "passed", 1),
        ("def test_fail(): assert False\n", "candidate_failed", 1),
        (
            "import pytest\n@pytest.mark.skip(reason='unavailable')\ndef test_skip(): pass\n",
            "test_failure",
            0,
        ),
        ("# no collected tests\n", "test_failure", 0),
    ],
)
def test_real_generic_provider_distinguishes_pass_fail_skip_and_empty(
    tmp_path, monkeypatch, source, expected, count
):
    file = Path(__file__).resolve().parents[1] / "providers/generic/runner.py"
    spec = importlib.util.spec_from_file_location("generic_runner", file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    dirs = {
        name + "_dir": tmp_path / name
        for name in ("context", "output", "project", "tests", "work")
    }
    for path in dirs.values():
        path.mkdir()
    write_json(dirs["context_dir"] / "input.json", {"obligations": ["VER-REAL"]})
    (dirs["tests_dir"] / "test_subject.py").write_text(source)
    monkeypatch.setattr(module.sys, "argv", ["runner.py"])
    result = module.main(**dirs)
    report = read_json(dirs["output_dir"] / "result.json")
    assert report["status"] == expected and report["test_count"] == count
    assert result == (0 if expected == "passed" else 1)
    if count == 0:
        assert not report["candidate_evaluated"]
