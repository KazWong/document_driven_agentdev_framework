# Architecture

## Responsibility boundaries

The main development bundle owns document/work-item orchestration, Codex role configuration, candidate Git mechanics, local verification, provider-neutral SCM publication, generic/firmware test orchestration, and project generation. The independently installed `ros2-humble-gazebo-test` bundle owns ROS 2 Humble/Gazebo execution and ROS-specific result production.

## Runtime topology

```text
/home/kazwong/codes/agents
├── projects/<project>/
│   ├── .agent/project.yaml                 tracked project/SCM identity
│   ├── .agent/policies.yaml                tracked project policy
│   ├── .agent/branching-policy.md          tracked Git reference
│   └── .agent/work-items/<id>/             ignored canonical operational record
└── .agent-state/
    ├── codex-home/
    ├── github-cli/
    ├── index/
    ├── worktrees/<project>/<id>/           disposable development worktree
    ├── verifiers/integration/.../<sha>/     disposable host-visible verifier checkout
    ├── cache/
    └── legacy-work-items/                  migration archive only
```

The canonical checkout owns work-item metadata. Linked worktrees resolve through Git's common directory to that same project. Deleting/recreating a worktree therefore does not delete documents, plans, trace, runs, approvals, or evidence.

## Verification topology

Local verification clones the exact candidate commit to a container-native temporary filesystem to avoid host/FUSE mode distortion. Integration verification clones the same candidate into the shared workspace so sibling Docker environments can consume it without touching the development worktree. Evidence is copied to the canonical work item before disposable verifier state is removed.

For the ROS Humble external lane, a Docker argv compatibility shim affects only the persistent `docker compose exec ... ros2-test-project` command and sources `/opt/ros/humble/setup.bash` in that actual exec process. Other Docker argv are forwarded unchanged.

## SCM topology

Project `.agent/project.yaml` selects `github` or `bitbucket`, remote, and base branch. The framework pushes only the work-item branch after exact-candidate verification/review, creates the PR, retrieves the remote PR head SHA, and enters `PR_OPEN` only when the remote SHA matches the reviewed candidate. Protected-branch merge remains outside automatic publication and requires human approval/provider protection.
