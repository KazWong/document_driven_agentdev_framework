# Supply immutable repository@sha256 references through the release build lock.
ARG NODE_IMAGE
ARG UBUNTU_IMAGE
FROM ${NODE_IMAGE} AS client_runtime
FROM ${UBUNTU_IMAGE}
ARG CODEX_VERSION
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates git gh docker.io python3 python3-venv \
    && rm -rf /var/lib/apt/lists/*
COPY --from=client_runtime /usr/local/ /usr/local/
RUN test -n "${CODEX_VERSION}" \
    && npm install --global "@openai/codex@${CODEX_VERSION}" \
    && npm cache clean --force
COPY requirements-runtime.txt /opt/framework/requirements-runtime.txt
RUN python3 -m venv /opt/framework-venv \
    && /opt/framework-venv/bin/pip install --no-cache-dir -r /opt/framework/requirements-runtime.txt
COPY src /opt/framework/src
COPY bin /opt/framework/bin
COPY providers /opt/framework/providers
ENV PATH=/opt/framework/bin:/opt/framework-venv/bin:$PATH
ENV PYTHONPATH=/opt/framework/src
WORKDIR /workspace
CMD ["sleep", "infinity"]
