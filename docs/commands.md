# Command reference

Generated from the repaired parser.

```text
usage: agentctl [-h] [--version] [--project PROJECT] [--state STATE]
                [--environments ENVIRONMENTS] [--work WORK]
                [--docker-runtime-profile DOCKER_RUNTIME_PROFILE] [--json]
                {doctor,init,new,status,propose,provider-preflight,tester-preflight,coder-preflight,reconcile,verified,review,diagnose,import-planning,import-test-design,role,run,sync-review,approve,start,accepting,accept,close,integrity,ci,recover-candidate,recover-role,promote,publish-pr,candidate,verify,resume,read,evidence,graph,explain,baseline,compact,retire,test-add,suite,test-export,env-seed,env-list,credential-register,env-build,env-retire,env-gc,env-recover-lease,env-publish,env-accept,migrate,rollback,hardware} ...

AI Agent Framework 2.1: approved changes, isolated execution, exact-candidate
evidence

positional arguments:
  {doctor,init,new,status,propose,provider-preflight,tester-preflight,coder-preflight,reconcile,verified,review,diagnose,import-planning,import-test-design,role,run,sync-review,approve,start,accepting,accept,close,integrity,ci,recover-candidate,recover-role,promote,publish-pr,candidate,verify,resume,read,evidence,graph,explain,baseline,compact,retire,test-add,suite,test-export,env-seed,env-list,credential-register,env-build,env-retire,env-gc,env-recover-lease,env-publish,env-accept,migrate,rollback,hardware}
    doctor              check backend readiness without claiming acceptance
    init                create a neutral repository; no technology scaffolding
    run                 resume automatic lifecycle until human review or a
                        diagnosed blocker
    sync-review         import the current GitHub/Bitbucket human approval
    read                inspect any public or independent artifact as the
                        operator
    hardware            show the separately approved physical-operation
                        boundary

options:
  -h, --help            show this help message and exit
  --version             show program's version number and exit
  --project PROJECT
  --state STATE         private controller directory outside the product
                        checkout
  --environments ENVIRONMENTS
                        shared environment registry directory
  --work WORK
  --docker-runtime-profile DOCKER_RUNTIME_PROFILE
                        operator-owned sandbox compatibility proof/config
  --json                emit the canonical machine projection
```

## doctor

```text
usage: agentctl doctor [-h]

options:
  -h, --help  show this help message and exit
```

## init

```text
usage: agentctl init [-h] --id ID

options:
  -h, --help  show this help message and exit
  --id ID
```

## new

```text
usage: agentctl new [-h] [--permission-file PERMISSION_FILE] request

positional arguments:
  request

options:
  -h, --help            show this help message and exit
  --permission-file PERMISSION_FILE
```

## status

```text
usage: agentctl status [-h]

options:
  -h, --help  show this help message and exit
```

## propose

```text
usage: agentctl propose [-h] --consequence CONSEQUENCE blueprint plan

positional arguments:
  blueprint
  plan

options:
  -h, --help            show this help message and exit
  --consequence CONSEQUENCE
```

## provider-preflight

```text
usage: agentctl provider-preflight [-h] selections

positional arguments:
  selections

options:
  -h, --help  show this help message and exit
```

## tester-preflight

```text
usage: agentctl tester-preflight [-h] suite job

positional arguments:
  suite
  job

options:
  -h, --help  show this help message and exit
```

## coder-preflight

```text
usage: agentctl coder-preflight [-h] job

positional arguments:
  job

options:
  -h, --help  show this help message and exit
```

## reconcile

```text
usage: agentctl reconcile [-h] job

positional arguments:
  job

options:
  -h, --help  show this help message and exit
```

## verified

```text
usage: agentctl verified [-h] job

positional arguments:
  job

options:
  -h, --help  show this help message and exit
```

## review

```text
usage: agentctl review [-h] job

positional arguments:
  job

options:
  -h, --help  show this help message and exit
```

## diagnose

```text
usage: agentctl diagnose [-h] job

positional arguments:
  job

options:
  -h, --help  show this help message and exit
```

## import-planning

```text
usage: agentctl import-planning [-h] job

positional arguments:
  job

options:
  -h, --help  show this help message and exit
```

## import-test-design

```text
usage: agentctl import-test-design [-h] job

positional arguments:
  job

options:
  -h, --help  show this help message and exit
```

## role

```text
usage: agentctl role [-h] --generation GENERATION --action ACTION
                     [--suite SUITE]
                     {planner,coder,tester,reviewer,safety_reviewer,debugger}

positional arguments:
  {planner,coder,tester,reviewer,safety_reviewer,debugger}

options:
  -h, --help            show this help message and exit
  --generation GENERATION
  --action ACTION
  --suite SUITE
```

## run

```text
usage: agentctl run [-h] --config CONFIG [--watch] [--timeout TIMEOUT]
                    [--poll-seconds POLL_SECONDS]

options:
  -h, --help            show this help message and exit
  --config CONFIG
  --watch
  --timeout TIMEOUT
  --poll-seconds POLL_SECONDS
```

## sync-review

```text
usage: agentctl sync-review [-h]

options:
  -h, --help  show this help message and exit
```

## approve

```text
usage: agentctl approve [-h] --actor ACTOR --digest DIGEST [--release]

options:
  -h, --help       show this help message and exit
  --actor ACTOR
  --digest DIGEST
  --release
```

## start

```text
usage: agentctl start [-h]

options:
  -h, --help  show this help message and exit
```

## accepting

```text
usage: agentctl accepting [-h]

options:
  -h, --help  show this help message and exit
```

## accept

```text
usage: agentctl accept [-h]

options:
  -h, --help  show this help message and exit
```

## close

```text
usage: agentctl close [-h]

options:
  -h, --help  show this help message and exit
```

## integrity

```text
usage: agentctl integrity [-h]

options:
  -h, --help  show this help message and exit
```

## ci

```text
usage: agentctl ci [-h]

options:
  -h, --help  show this help message and exit
```

## recover-candidate

```text
usage: agentctl recover-candidate [-h]

options:
  -h, --help  show this help message and exit
```

## promote

```text
usage: agentctl promote [-h] [--authorize-remote]

options:
  -h, --help          show this help message and exit
  --authorize-remote
```

## publish-pr

```text
usage: agentctl publish-pr [-h] --actor ACTOR --title TITLE --body-file
                           BODY_FILE

options:
  -h, --help            show this help message and exit
  --actor ACTOR
  --title TITLE
  --body-file BODY_FILE
```

## candidate

```text
usage: agentctl candidate [-h] [--subject SUBJECT] trace

positional arguments:
  trace

options:
  -h, --help         show this help message and exit
  --subject SUBJECT
```

## verify

```text
usage: agentctl verify [-h] --action ACTION [--final] environment

positional arguments:
  environment

options:
  -h, --help       show this help message and exit
  --action ACTION
  --final
```

## resume

```text
usage: agentctl resume [-h] --actor ACTOR [--repair-source]

options:
  -h, --help       show this help message and exit
  --actor ACTOR
  --repair-source
```

## read

```text
usage: agentctl read [-h] [--revision REVISION] [--content] artifact

positional arguments:
  artifact

options:
  -h, --help           show this help message and exit
  --revision REVISION
  --content
```

## evidence

```text
usage: agentctl evidence [-h] digest

positional arguments:
  digest

options:
  -h, --help  show this help message and exit
```

## graph

```text
usage: agentctl graph [-h] [--focus FOCUS] [--view VIEW] [--limit LIMIT]
                      [--baseline BASELINE] [--format {text,json,mermaid,svg}]
                      [--output OUTPUT]

options:
  -h, --help            show this help message and exit
  --focus FOCUS
  --view VIEW
  --limit LIMIT
  --baseline BASELINE
  --format {text,json,mermaid,svg}
  --output OUTPUT
```

## explain

```text
usage: agentctl explain [-h] artifact

positional arguments:
  artifact

options:
  -h, --help  show this help message and exit
```

## baseline

```text
usage: agentctl baseline [-h] [--compact] id label

positional arguments:
  id
  label

options:
  -h, --help  show this help message and exit
  --compact
```

## compact

```text
usage: agentctl compact [-h]

options:
  -h, --help  show this help message and exit
```

## retire

```text
usage: agentctl retire [-h] --reason REASON artifact

positional arguments:
  artifact

options:
  -h, --help       show this help message and exit
  --reason REASON
```

## test-add

```text
usage: agentctl test-add [-h] --path PATH --visibility
                         {development,independent} --obligation OBLIGATION
                         [--revision REVISION]
                         id source

positional arguments:
  id
  source

options:
  -h, --help            show this help message and exit
  --path PATH
  --visibility {development,independent}
  --obligation OBLIGATION
  --revision REVISION
```

## suite

```text
usage: agentctl suite [-h] --obligation OBLIGATION --rationale RATIONALE
                      [--revision REVISION]
                      id cases [cases ...]

positional arguments:
  id
  cases

options:
  -h, --help            show this help message and exit
  --obligation OBLIGATION
  --rationale RATIONALE
  --revision REVISION
```

## test-export

```text
usage: agentctl test-export [-h] [--include-independent] suite directory

positional arguments:
  suite
  directory

options:
  -h, --help            show this help message and exit
  --include-independent
```

## env-seed

```text
usage: agentctl env-seed [-h] --actor ACTOR --digest DIGEST
                         --verification-note VERIFICATION_NOTE
                         release

positional arguments:
  release

options:
  -h, --help            show this help message and exit
  --actor ACTOR
  --digest DIGEST
  --verification-note VERIFICATION_NOTE
```

## env-list

```text
usage: agentctl env-list [-h]

options:
  -h, --help  show this help message and exit
```

## credential-register

```text
usage: agentctl credential-register [-h] name file

positional arguments:
  name
  file

options:
  -h, --help  show this help message and exit
```

## env-build

```text
usage: agentctl env-build [-h] --recipe RECIPE [--network] source

positional arguments:
  source

options:
  -h, --help       show this help message and exit
  --recipe RECIPE
  --network
```

## env-retire

```text
usage: agentctl env-retire [-h] generation

positional arguments:
  generation

options:
  -h, --help  show this help message and exit
```

## env-gc

```text
usage: agentctl env-gc [-h] [--apply]

options:
  -h, --help  show this help message and exit
  --apply
```

## env-recover-lease

```text
usage: agentctl env-recover-lease [-h] --actor ACTOR --verification-note
                                  VERIFICATION_NOTE
                                  token

positional arguments:
  token

options:
  -h, --help            show this help message and exit
  --actor ACTOR
  --verification-note VERIFICATION_NOTE
```

## env-publish

```text
usage: agentctl env-publish [-h] release

positional arguments:
  release

options:
  -h, --help  show this help message and exit
```

## env-accept

```text
usage: agentctl env-accept [-h] release

positional arguments:
  release

options:
  -h, --help  show this help message and exit
```

## migrate

```text
usage: agentctl migrate [-h] [--apply] [--digest DIGEST] legacy target

positional arguments:
  legacy
  target

options:
  -h, --help       show this help message and exit
  --apply
  --digest DIGEST
```

## rollback

```text
usage: agentctl rollback [-h] --actor ACTOR target

positional arguments:
  target

options:
  -h, --help     show this help message and exit
  --actor ACTOR
```

## hardware

```text
usage: agentctl hardware [-h]

options:
  -h, --help  show this help message and exit
```

### Durable role/candidate recovery

`recover-role` inspects the current checkout's controller-generated file-application journals. It rolls back uncommitted output, retains committed output, and refuses unknown edits. `recover-candidate` resumes only an exact pending candidate for the current work item/package, whether the Git commit has already occurred or not. Neither command grants approval or manufactures passing verification.
