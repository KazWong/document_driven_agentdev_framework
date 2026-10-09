# Command reference — v2.1.0

Generated from the implemented CLI. Global options precede the command. Each command prints readable output by default; `--json` requests machine output. Exit 0 means the command completed; exit 2 means blocked/invalid input. A completed command is not necessarily a passed acceptance result: inspect recorded status.

```text
usage: agentctl [-h] [--version] [--project PROJECT] [--state STATE]
                [--environments ENVIRONMENTS] [--work WORK] [--json]
                {doctor,init,new,status,propose,provider-preflight,tester-preflight,coder-preflight,reconcile,verified,review,diagnose,import-planning,import-test-design,role,approve,start,accepting,accept,close,integrity,ci,recover-candidate,promote,publish-pr,candidate,verify,resume,read,evidence,graph,explain,baseline,compact,retire,test-add,suite,test-export,env-seed,env-list,credential-register,env-build,env-retire,env-gc,env-recover-lease,env-publish,env-accept,migrate,rollback,hardware}
                ...
```

`agentctl`, `projectctl`, `testctl` and `scmctl` expose the same controller command set. `hardwarectl` always reports the separately reviewed physical-operation boundary.

## doctor

```text
usage: agentctl doctor [-h]
```

## init

```text
usage: agentctl init [-h] --id ID
```

## new

```text
usage: agentctl new [-h] [--permission-file PERMISSION_FILE] request
```

## status

```text
usage: agentctl status [-h]
```

## propose

```text
usage: agentctl propose [-h] --consequence CONSEQUENCE blueprint plan
```

## provider-preflight

```text
usage: agentctl provider-preflight [-h] selections
```

## tester-preflight

```text
usage: agentctl tester-preflight [-h] suite job
```

## coder-preflight

```text
usage: agentctl coder-preflight [-h] job
```

## reconcile

```text
usage: agentctl reconcile [-h] job
```

## verified

```text
usage: agentctl verified [-h] job
```

## review

```text
usage: agentctl review [-h] job
```

## diagnose

```text
usage: agentctl diagnose [-h] job
```

## import-planning

```text
usage: agentctl import-planning [-h] job
```

## import-test-design

```text
usage: agentctl import-test-design [-h] job
```

## role

```text
usage: agentctl role [-h] --generation GENERATION --action ACTION
                     [--suite SUITE]
                     {planner,coder,tester,reviewer,safety_reviewer,debugger}
```

## approve

```text
usage: agentctl approve [-h] --actor ACTOR --digest DIGEST [--release]
```

## start

```text
usage: agentctl start [-h]
```

## accepting

```text
usage: agentctl accepting [-h]
```

## accept

```text
usage: agentctl accept [-h]
```

## close

```text
usage: agentctl close [-h]
```

## integrity

```text
usage: agentctl integrity [-h]
```

## ci

```text
usage: agentctl ci [-h]
```

## recover-candidate

```text
usage: agentctl recover-candidate [-h]
```

## promote

```text
usage: agentctl promote [-h] [--authorize-remote]
```

## publish-pr

```text
usage: agentctl publish-pr [-h] --actor ACTOR --title TITLE --body-file
                           BODY_FILE
```

## candidate

```text
usage: agentctl candidate [-h] [--subject SUBJECT] trace
```

## verify

```text
usage: agentctl verify [-h] --action ACTION [--final] environment
```

## resume

```text
usage: agentctl resume [-h] --actor ACTOR [--repair-source]
```

## read

```text
usage: agentctl read [-h] [--revision REVISION] [--content] artifact
```

## evidence

```text
usage: agentctl evidence [-h] digest
```

## graph

```text
usage: agentctl graph [-h] [--focus FOCUS] [--view VIEW] [--limit LIMIT]
                      [--baseline BASELINE] [--format {text,json,mermaid,svg}]
                      [--output OUTPUT]
```

## explain

```text
usage: agentctl explain [-h] artifact
```

## baseline

```text
usage: agentctl baseline [-h] [--compact] id label
```

## compact

```text
usage: agentctl compact [-h]
```

## retire

```text
usage: agentctl retire [-h] --reason REASON artifact
```

## test-add

```text
usage: agentctl test-add [-h] --path PATH --visibility
                         {development,independent} --obligation OBLIGATION
                         [--revision REVISION]
                         id source
```

## suite

```text
usage: agentctl suite [-h] --obligation OBLIGATION --rationale RATIONALE
                      [--revision REVISION]
                      id cases [cases ...]
```

## test-export

```text
usage: agentctl test-export [-h] [--include-independent] suite directory
```

## env-seed

```text
usage: agentctl env-seed [-h] --actor ACTOR --digest DIGEST
                         --verification-note VERIFICATION_NOTE
                         release
```

## env-list

```text
usage: agentctl env-list [-h]
```

## credential-register

```text
usage: agentctl credential-register [-h] name file
```

## env-build

```text
usage: agentctl env-build [-h] --recipe RECIPE [--network] source
```

## env-retire

```text
usage: agentctl env-retire [-h] generation
```

## env-gc

```text
usage: agentctl env-gc [-h] [--apply]
```

## env-recover-lease

```text
usage: agentctl env-recover-lease [-h] --actor ACTOR --verification-note
                                  VERIFICATION_NOTE
                                  token
```

## env-publish

```text
usage: agentctl env-publish [-h] release
```

## env-accept

```text
usage: agentctl env-accept [-h] release
```

## migrate

```text
usage: agentctl migrate [-h] [--apply] [--digest DIGEST] legacy target
```

## rollback

```text
usage: agentctl rollback [-h] --actor ACTOR target
```

## hardware

```text
usage: agentctl hardware [-h]
```
