FROM python:3.12-slim

# The Docker CLI (with the compose plugin) is needed because Compose v2 has
# no stable Python API - it ships as a CLI plugin. This installs just the
# CLI packages, not a full Docker daemon.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl gnupg \
    && install -m 0755 -d /etc/apt/keyrings \
    && curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc \
    && chmod a+r /etc/apt/keyrings/docker.asc \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian bookworm stable" \
        > /etc/apt/sources.list.d/docker.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends docker-ce-cli docker-compose-plugin \
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
