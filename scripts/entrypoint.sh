#!/usr/bin/env sh
set -e

SOCKET="/var/run/docker.sock"

if [ -e "$SOCKET" ]; then
    SOCKET_GID=$(stat -c '%g' "$SOCKET")

    # If the group ID doesn't exist inside the container, create a group for it
    if ! getent group "$SOCKET_GID" >/dev/null 2>&1; then
        groupadd -g "$SOCKET_GID" docker-host
    fi

    # Add non-root user 'orchestrator' to the host socket's group
    usermod -aG "$SOCKET_GID" orchestrator 2>/dev/null || gpasswd -a orchestrator "$SOCKET_GID" 2>/dev/null

    # Drop root privileges and execute the application
    exec gosu orchestrator "$@"
fi

exec gosu orchestrator "$@"
