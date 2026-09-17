FROM ubuntu:24.04
ARG DEBIAN_FRONTEND=noninteractive
ARG USERNAME=kazwong
ARG USER_UID=1000
ARG USER_GID=1000
RUN apt-get update && apt-get install -y --no-install-recommends \
    avrdude build-essential ca-certificates cmake curl dfu-util gcc-arm-none-eabi \
    gdb-multiarch git jq libnewlib-arm-none-eabi make ninja-build openocd \
    picocom python3 python3-pip python3-venv qemu-system-arm shellcheck usbutils \
    && python3 -m pip install --break-system-packages --no-cache-dir platformio \
    && rm -rf /var/lib/apt/lists/*
RUN set -eux; \
    existing_group="$(getent group "${USER_GID}" | cut -d: -f1 || true)"; \
    if [ -n "$existing_group" ]; then groupmod --new-name "$USERNAME" "$existing_group"; else groupadd --gid "$USER_GID" "$USERNAME"; fi; \
    existing_user="$(getent passwd "${USER_UID}" | cut -d: -f1 || true)"; \
    if [ -n "$existing_user" ]; then usermod --login "$USERNAME" --home "/home/$USERNAME" --move-home "$existing_user"; else useradd --uid "$USER_UID" --gid "$USER_GID" --create-home --shell /bin/bash "$USERNAME"; fi; \
    mkdir -p /home/kazwong/codes/agents; chown -R "$USER_UID:$USER_GID" /home/kazwong
COPY docker/firmware/firmware-test /usr/local/bin/firmware-test
RUN chmod +x /usr/local/bin/firmware-test
USER ${USERNAME}
WORKDIR /home/kazwong/codes/agents
CMD ["sleep", "infinity"]
