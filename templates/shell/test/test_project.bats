#!/usr/bin/env bats

@test "command prints its project name" {
  run ./bin/__PROJECT_NAME__
  [ "$status" -eq 0 ]
  [[ "$output" == *"__PROJECT_NAME__"* ]]
}
