FROM ubuntu:24.04
ARG DEBIAN_FRONTEND=noninteractive
ARG USERNAME=kazwong
ARG USER_UID=1000
ARG USER_GID=1000
RUN apt-get update && apt-get install -y --no-install-recommends \
    bats build-essential ca-certificates ccache clang clang-format clang-tidy cmake \
    cppcheck gdb git jq lcov make ninja-build python3 python3-pip python3-pytest \
    python3-venv shellcheck valgrind \
    && rm -rf /var/lib/apt/lists/*
RUN set -eux; \
    existing_group="$(getent group "${USER_GID}" | cut -d: -f1 || true)"; \
    if [ -n "$existing_group" ]; then groupmod --new-name "$USERNAME" "$existing_group"; else groupadd --gid "$USER_GID" "$USERNAME"; fi; \
    existing_user="$(getent passwd "${USER_UID}" | cut -d: -f1 || true)"; \
    if [ -n "$existing_user" ]; then usermod --login "$USERNAME" --home "/home/$USERNAME" --move-home "$existing_user"; else useradd --uid "$USER_UID" --gid "$USER_GID" --create-home --shell /bin/bash "$USERNAME"; fi; \
    mkdir -p /home/kazwong/codes/agents; chown -R "$USER_UID:$USER_GID" /home/kazwong
COPY docker/generic/generic-test /usr/local/bin/generic-test
RUN chmod +x /usr/local/bin/generic-test
USER ${USERNAME}
WORKDIR /home/kazwong/codes/agents
CMD ["sleep", "infinity"]
