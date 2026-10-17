# Utility scripts

These scripts support development, container start-up, and user-level systemd
deployment for the service orchestrator.

| Script | Purpose |
| --- | --- |
| [`bootstrap.sh`](bootstrap.sh) | Sets up a development checkout. It checks for `uv` and a Git checkout, installs the locked project dependencies (including extras and development dependencies), then installs the pre-commit and pre-push hooks. Run it from within the checkout. |
| [`entrypoint.sh`](entrypoint.sh) | Container entrypoint that starts the supplied command as the unprivileged `orchestrator` user. When the Docker socket is present, it detects the socket's group ID and adds that user to the corresponding group before dropping privileges. |
| [`install-systemd.sh`](install-systemd.sh) | Installs the user-level systemd units. It creates the Achterhus configuration directory and example environment file when needed, links the service and timer units, verifies them, and enables and starts the nightly and weekly timers. |
| [`run-coverage.sh`](run-coverage.sh) | Runs the full pytest suite with coverage for `orchestrator` and enforces an 80% minimum. It always prints a terminal report with missing lines; pass `--html`, `--xml`, or `--all` to also generate HTML, XML, or both reports. |
