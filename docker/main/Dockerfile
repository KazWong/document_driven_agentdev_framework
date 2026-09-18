FROM node:22-bookworm-slim AS node_runtime

FROM ubuntu:24.04

ARG DEBIAN_FRONTEND=noninteractive
ARG USERNAME=kazwong
ARG USER_UID=1000
ARG USER_GID=1000
ARG DOCKER_GID=999
ARG CODEX_VERSION=latest

COPY --from=node_runtime /usr/local/ /usr/local/

RUN apt-get update && apt-get install -y --no-install-recommends \
    bash-completion bats bubblewrap build-essential ca-certificates ccache clang clang-format \
    clang-tidy clang-tools clangd cmake cppcheck curl docker-compose-v2 docker.io \
    file gdb git git-lfs gnupg jq less lcov lldb locales make nano ninja-build \
    openssh-client pkg-config pipx python3 python3-dev python3-jsonschema python3-pip \
    python3-venv python3-yaml ripgrep rsync shellcheck unzip valgrind vim zip \
    && locale-gen en_US.UTF-8 \
    && rm -rf /var/lib/apt/lists/*

RUN npm install --global "@openai/codex@${CODEX_VERSION}" \
    && npm cache clean --force

RUN set -eux; \
    existing_group="$(getent group "${USER_GID}" | cut -d: -f1 || true)"; \
    if [ -n "$existing_group" ]; then groupmod --new-name "$USERNAME" "$existing_group"; else groupadd --gid "$USER_GID" "$USERNAME"; fi; \
    existing_user="$(getent passwd "${USER_UID}" | cut -d: -f1 || true)"; \
    if [ -n "$existing_user" ]; then usermod --login "$USERNAME" --home "/home/$USERNAME" --move-home "$existing_user"; else useradd --uid "$USER_UID" --gid "$USER_GID" --create-home --shell /bin/bash "$USERNAME"; fi; \
    docker_group="$(getent group "${DOCKER_GID}" | cut -d: -f1 || true)"; \
    if [ -z "$docker_group" ]; then docker_group=docker-host; groupadd --gid "$DOCKER_GID" "$docker_group"; fi; \
    usermod -aG "$docker_group" "$USERNAME"; \
    mkdir -p /home/kazwong/codes/agents /opt/robotics-agent-env; \
    chown -R "$USER_UID:$USER_GID" /home/kazwong /opt/robotics-agent-env

COPY --chown=${USER_UID}:${USER_GID} bin /opt/robotics-agent-env/bin
COPY --chown=${USER_UID}:${USER_GID} src /opt/robotics-agent-env/src
COPY --chown=${USER_UID}:${USER_GID} config /opt/robotics-agent-env/config
COPY --chown=${USER_UID}:${USER_GID} schemas /opt/robotics-agent-env/schemas
COPY --chown=${USER_UID}:${USER_GID} examples /opt/robotics-agent-env/examples
COPY --chown=${USER_UID}:${USER_GID} templates /opt/robotics-agent-env/templates
COPY --chown=${USER_UID}:${USER_GID} docker /opt/robotics-agent-env/docker
COPY --chown=${USER_UID}:${USER_GID} compose.yaml compose.hardware.yaml /opt/robotics-agent-env/
COPY --chown=${USER_UID}:${USER_GID} .codex /opt/robotics-agent-env/.codex
COPY --chown=${USER_UID}:${USER_GID} scripts/entrypoint.sh /usr/local/bin/robotics-agent-entrypoint

RUN chmod +x /opt/robotics-agent-env/bin/* /opt/robotics-agent-env/docker/generic/generic-test /opt/robotics-agent-env/docker/firmware/firmware-test /usr/local/bin/robotics-agent-entrypoint \
    && ln -s /opt/robotics-agent-env/bin/agentctl /usr/local/bin/agentctl \
    && ln -s /opt/robotics-agent-env/bin/testctl /usr/local/bin/testctl \
    && ln -s /opt/robotics-agent-env/bin/bitbucket-pr /usr/local/bin/bitbucket-pr \
    && ln -s /opt/robotics-agent-env/bin/hardwarectl /usr/local/bin/hardwarectl \
    && ln -s /opt/robotics-agent-env/bin/projectctl /usr/local/bin/projectctl

ENV LANG=en_US.UTF-8 \
    LC_ALL=en_US.UTF-8 \
    ROBOTICS_AGENT_ENV_ROOT=/opt/robotics-agent-env \
    AGENT_WORKSPACE_ROOT=/home/kazwong/codes/agents \
    AGENT_STATE_ROOT=/home/kazwong/codes/agents/.agent-state \
    CODEX_HOME=/home/kazwong/codes/agents/.agent-state/codex-home \
    PYTHONPATH=/opt/robotics-agent-env/src \
    PATH=/opt/robotics-agent-env/bin:/home/kazwong/.local/bin:${PATH}

USER ${USERNAME}
WORKDIR /home/kazwong/codes/agents
ENTRYPOINT ["/usr/local/bin/robotics-agent-entrypoint"]
CMD ["sleep", "infinity"]
