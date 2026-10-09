# Framework development contract

1. User requirements and approved Engineering Change Packages govern work. The user approved ECP-V210-001-r1 and a clean v2.1 rewrite; no additional approval of the same design is required.
2. Preserve stable requirement/component/interface/verification identities and historical evidence. Keep implementation, Blueprint, tests and current architecture documentation aligned.
3. Planner owns design, Tester owns test design and concrete tests, Coder owns production implementation, Reviewer/Safety Reviewer assess the exact candidate. Debugger is read-only and on demand. Roles cannot approve their own work.
4. Only the trusted controller creates candidate commits and performs SCM mutations. Work on the work-item feature branch, never protected branches. Never force-push. Remote publication and hardware actions require explicit authorization.
5. Required verification executes through the approved provider/environment on an immutable candidate. Advisory host checks do not establish authoritative release acceptance. Report unrun live gates honestly.
6. Never change requirements, thresholds, policy or tests merely to obtain a pass. Correct implementation bugs within approved scope; architecture changes require a revised package.
7. Store controller state outside agent-visible snapshots; protect independent tests, credentials and approval records. Unavailable isolation blocks role execution.
8. Keep runtime code technology-neutral. Domain behavior belongs in provider projects, not core branches or language-based risk classification.
