from __future__ import annotations

WORKSPACE_DEFAULT = "/home/kazwong/codes/agents"
STATE_DIR_NAME = ".agent-state"

RISK_POLICY = {
    "R0": {"plan_approvals": 1, "merge_approvals": 1, "safety_review": False, "hardware_approvals": 0, "requires_local": False, "requires_integration": False},
    "R1": {"plan_approvals": 1, "merge_approvals": 1, "safety_review": False, "hardware_approvals": 0, "requires_local": True, "requires_integration": False},
    "R2": {"plan_approvals": 1, "merge_approvals": 2, "safety_review": True, "hardware_approvals": 0, "requires_local": True, "requires_integration": True},
    "R3": {"plan_approvals": 1, "merge_approvals": 2, "safety_review": True, "hardware_approvals": 2, "requires_local": True, "requires_integration": True},
}

STABLE_STATES = {
    "INTAKE", "PLANNED", "PLAN_APPROVED", "IMPLEMENTED", "LOCALLY_VERIFIED",
    "ENV_VERIFIED", "REVIEWED", "PR_OPEN", "PR_READY", "CI_VERIFIED", "MERGE_APPROVED",
    "PROMOTED", "CLOSED", "DIAGNOSING", "DIAGNOSED", "BLOCKED",
}
TRANSIENT_STATES = {"PLANNING", "IMPLEMENTING", "LOCAL_VERIFYING", "ENV_VERIFYING", "REVIEWING", "PR_PREPARING", "PR_CREATING"}
ALL_STATES = STABLE_STATES | TRANSIENT_STATES

ROLE_SANDBOX = {
    "planner": "read-only",
    "coder": "workspace-write",
    "tester": "read-only",
    "integration_tester": "read-only",
    "debugger": "read-only",
    "reviewer": "read-only",
    "review_requester": "read-only",
    "safety_reviewer": "read-only",
}
ROLE_ARTIFACT = {
    "planner": "plan.md",
    "coder": "implementation-report.md",
    "tester": "local-test-review.md",
    "integration_tester": "integration-test-review.md",
    "debugger": "diagnosis.md",
    "reviewer": "review.md",
    "review_requester": "pull-request.md",
    "safety_reviewer": "safety-review.md",
}
PROTECTED_BRANCHES = {"main", "master", "develop", "development", "release"}
ALLOWED_LOCAL_EXECUTABLES = {"bash", "bats", "cmake", "colcon", "cppcheck", "ctest", "make", "meson", "ninja", "pytest", "python", "python3", "ruff", "sh", "shellcheck"}
BLOCKED_EXECUTABLES = {"avrdude", "dd", "dfu-util", "docker", "docker-compose", "fdisk", "git", "halt", "mkfs", "mount", "openocd", "parted", "pio", "platformio", "poweroff", "reboot", "shutdown", "sudo", "umount", "west"}
BLOCKED_ARGUMENTS = {"--privileged", "--device", "--pid=host", "--network=host", "--ipc=host"}
