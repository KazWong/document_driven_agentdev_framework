# Migration from 1.0.0 to 2.0.0

## Breaking changes

1. Remove any embedded `ros2-gazebo`/Jazzy service from the main Compose project.
2. Install `ros2-humble-gazebo-test` under `infrastructure/` and verify `ros2-test` is executable.
3. Replace free-form commands such as `agentctl plan "text"` with a work-item ID:

   ```bash
   agentctl new work-item.yaml
   agentctl plan RBT-123
   ```

4. Update ROS manifests to use `lane: ros2-humble`. The old `ros2-gazebo` name remains an alias only at the `testctl` boundary.
5. Add `project_kind` and `risk_class` to every manifest.
6. Use `agentctl approve` for plan, PR, merge, and hardware gates.
7. Do not call Docker or firmware flash commands from an agent prompt. Use deterministic `testctl` or human-operated `hardwarectl` paths.

## State preservation

Keep the existing `/home/kazwong/codes/agents/.agent-state` directory. Version 2 uses separate `work-items`, `worktrees`, and cache subdirectories. Existing Codex authentication remains under `codex-home`.

Run:

```bash
./scripts/sync-codex-config.sh --force
```

The sync script backs up existing managed files before replacing them.

## Project migration

Copy `.agent`, `.codex`, `AGENTS.md`, and `.bitbucket/pull_request_template.md` from a newly generated v2 project. Add a deterministic `scripts/ci/verify.sh`. Do not copy generated source examples over existing production code.
