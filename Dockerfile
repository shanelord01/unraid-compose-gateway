FROM python:3.12-slim

# Docker Compose version this image runs. It MUST match the Compose version
# the host's own tooling uses (on Unraid: the standalone docker-compose
# binary shipped by the Compose Manager plugin, `docker-compose version`
# on the host). Compose computes a per-service config hash and stores it
# on each container; different Compose versions hash the same YAML
# differently, so if this image and the host tool disagree, every `up`
# from either side force-recreates the whole project. The runtime guard in
# compose_version.py refuses `up` when it detects that, but the fix is to
# keep this pinned to the host version.
ARG COMPOSE_VERSION=2.40.3
ENV GATEWAY_COMPOSE_VERSION=${COMPOSE_VERSION}

# Docker CLI from Docker's apt repo (its version does not affect the config
# hash), and the Compose plugin as a pinned release binary rather than the
# apt package, which tracks whatever is current and cannot be held to the
# host's version.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl gnupg \
    && install -m 0755 -d /etc/apt/keyrings \
    && curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc \
    && chmod a+r /etc/apt/keyrings/docker.asc \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian bookworm stable" \
        > /etc/apt/sources.list.d/docker.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends docker-ce-cli \
    && arch="$(uname -m)" \
    && install -m 0755 -d /usr/libexec/docker/cli-plugins \
    && curl -fsSL "https://github.com/docker/compose/releases/download/v${COMPOSE_VERSION}/docker-compose-linux-${arch}" \
        -o /usr/libexec/docker/cli-plugins/docker-compose \
    && chmod 0755 /usr/libexec/docker/cli-plugins/docker-compose \
    && test "$(docker compose version --short)" = "${COMPOSE_VERSION}" \
    && apt-get purge -y --auto-remove curl gnupg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY unraid_compose_gateway/ unraid_compose_gateway/

# Runs as root: it needs to reach the mounted docker.sock, and there is no
# safe way to drop privileges on that socket from inside the container -
# the access it grants comes from group membership on the socket file
# itself. Scope what this container can do by not mounting more than
# docker.sock, COMPOSE_PROJECTS_DIR, and (optionally) PLUGIN_DIR.
EXPOSE 8080
CMD ["python", "-m", "unraid_compose_gateway"]
