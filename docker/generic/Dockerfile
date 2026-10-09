ARG UBUNTU_IMAGE
FROM ${UBUNTU_IMAGE}
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates git python3 python3-venv \
    && rm -rf /var/lib/apt/lists/*
COPY requirements-dev.txt requirements-runtime.txt /opt/framework/
RUN python3 -m venv /opt/test-venv \
    && /opt/test-venv/bin/pip install --no-cache-dir -r /opt/framework/requirements-dev.txt
COPY providers/generic /opt/providers/generic
ENV PATH=/opt/test-venv/bin:$PATH
ENV PYTHONDONTWRITEBYTECODE=1
WORKDIR /work
CMD ["sleep", "infinity"]
