SHELL := /usr/bin/env bash
COMPOSE := docker compose -f compose.yaml
NAME ?=

.PHONY: configure build up shell down logs doctor qa qa-docker smoke smoke-generic smoke-firmware smoke-ros2 project-c project-cpp project-python project-shell package

configure:
	./scripts/bootstrap-host.sh

build:
	$(COMPOSE) --profile test build

up:
	$(COMPOSE) up -d main-development

shell:
	$(COMPOSE) exec main-development bash

down:
	$(COMPOSE) --profile test down --remove-orphans

logs:
	$(COMPOSE) logs -f main-development

doctor:
	$(COMPOSE) exec main-development agentctl doctor

smoke: smoke-generic smoke-firmware smoke-ros2

smoke-generic:
	$(COMPOSE) exec main-development testctl smoke generic

smoke-firmware:
	$(COMPOSE) exec main-development testctl smoke firmware

smoke-ros2:
	$(COMPOSE) exec main-development testctl smoke ros2-humble

project-c:
	@test -n "$(NAME)" || (echo 'Set NAME=<project-name>' >&2; exit 2)
	$(COMPOSE) exec main-development projectctl create --type c --name "$(NAME)"

project-cpp:
	@test -n "$(NAME)" || (echo 'Set NAME=<project-name>' >&2; exit 2)
	$(COMPOSE) exec main-development projectctl create --type cpp --name "$(NAME)"

project-python:
	@test -n "$(NAME)" || (echo 'Set NAME=<project-name>' >&2; exit 2)
	$(COMPOSE) exec main-development projectctl create --type python --name "$(NAME)"

project-shell:
	@test -n "$(NAME)" || (echo 'Set NAME=<project-name>' >&2; exit 2)
	$(COMPOSE) exec main-development projectctl create --type shell --name "$(NAME)"

qa:
	./scripts/qa.sh

qa-docker:
	./scripts/qa.sh --with-docker

package: qa
	./scripts/package.sh
