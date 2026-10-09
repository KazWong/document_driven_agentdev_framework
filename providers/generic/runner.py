"""Generic Python test action. This belongs to a provider, never core dispatch."""

import json
import os
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET


def main(
    *,
    context_dir=Path("/context"),
    output_dir=Path("/output"),
    project_dir=Path("/project"),
    tests_dir=Path("/tests"),
    work_dir=Path("/work"),
):
    context = json.loads((context_dir / "input.json").read_text())
    if "--resolve" in sys.argv:
        capability = context["requirement"]["capability"]
        supported = ["python-tests", "framework-bootstrap"]
        constraints = {"platform": "linux", "architecture": "amd64"}
        compatible = capability in supported and all(
            constraints.get(k) == v
            for k, v in context["requirement"]["constraints"].items()
        )
        (output_dir / "resolution.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "compatible": compatible,
                    "capabilities": [
                        c for c in supported if c in context["capabilities"]
                    ],
                    "constraints": constraints,
                    "findings": (
                        []
                        if compatible
                        else ["Unsupported generic provider requirement"]
                    ),
                }
            )
            + "\n"
        )
        return 0
    output = output_dir
    report = output / "junit.xml"
    env = {
        **os.environ,
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        "PYTHONPATH": str(project_dir / "src") + os.pathsep + str(project_dir),
    }
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "--junitxml=" + str(report),
            str(tests_dir),
        ],
        cwd=work_dir,
        env=env,
        check=False,
    )
    count = 0
    skipped = 0
    if report.is_file():
        tree = ET.parse(report).getroot()
        cases = tree.findall(".//testcase")
        skipped = sum(case.find("skipped") is not None for case in cases)
        count = len(cases) - skipped
    passed = result.returncode == 0 and count > 0 and skipped == 0
    value = {
        "schema_version": 1,
        "status": (
            "passed"
            if passed
            else "candidate_failed" if result.returncode == 1 else "test_failure"
        ),
        "candidate_evaluated": count > 0 and result.returncode in (0, 1),
        "test_count": count,
        "obligation_ids": context["obligations"],
        "failure_stage": "none" if passed else "execute",
    }
    (output / "result.json").write_text(json.dumps(value, sort_keys=True) + "\n")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
