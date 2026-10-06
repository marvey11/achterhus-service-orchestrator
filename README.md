# Achterhus Service Orchestrator

The Achterhus service orchestrator resolves Docker service dependency graphs, ensures the
necessary image is current, and executes the configured services in dependency order.
Each invocation reads the configuration and runs the selected graph once, then exits.
It does not stay running to watch for or schedule future executions.

## Responsibilities

- Read and validate a YAML service configuration
- Resolve service execution order with `graphlib.TopologicalSorter`
- Pull or refresh an image only when the remote GHCR manifest differs
- Execute containers with their required environment, command and volumes
- Enforce an execution timeout through the container watchguard
- Register each service run and report its lifecycle to the [Telemetry API](https://github.com/marvey11/achterhus-telemetry-api) when `TELEMETRY_API_URL` is configured

For each service execution, the orchestrator creates one UUID, registers it with
the Telemetry API in `SCHEDULED` state, and passes the same value to the container
as `SERVICE_RUN_ID`. It reports `IMAGE_PULLING` when it pulls an updated image and
`STARTING` before creating and starting the container. The service's Telemetry
Client uses that run ID to report application status and events; it must not
register a second run. The application reports `SUCCESS` when its work completes;
the Watchguard does not repeat that terminal status after observing a clean
container exit. It reports exceptional outcomes such as timeouts and
out-of-memory termination. Telemetry reporting is disabled when
`TELEMETRY_API_URL` is empty or unset.

## Configuration format

The `services` section defines each eligible service once. The `graphs` section
then names execution graphs and lists their service dependencies. Each graph is a
mapping from service names to the services that must complete first. Use an empty
list for a service with no dependencies in that graph.

```yaml
services:
  postgres:
    image: ghcr.io/example/postgres:latest
    environment:
      POSTGRES_DB: telemetry
      POSTGRES_USER: telemetry
      POSTGRES_PASSWORD: change-me
    volumes:
      - postgres-data:/var/lib/postgresql/data

  api:
    image: ghcr.io/marvey11/achterhus-telemetry-api:latest
    environment:
      TELEMETRY_API_URL: http://telemetry-api:8000
    command: ["python", "-m", "telemetry.main"]
    timeout_seconds: 300

  reports:
    image: ghcr.io/example/reports:latest

  backup:
    image: ghcr.io/example/backup:latest

graphs:
  nightly:
    postgres: []
    api: [postgres]
    backup: [postgres, api]

  weekly:
    postgres: []
    api: [postgres]
    reports: [api]
    backup: [postgres, api, reports]
```

Every service and dependency named in a graph must be defined under `services`.
Dependencies must also appear in that graph. Service options may include `image`,
`environment`, `command`, `volumes`, `timeout_seconds`, `working_dir`, and `network`.

## Command line

Install the project and run the orchestrator with a YAML configuration file:

```bash
uv run orchestrator services.yaml --graph weekly
```

The configuration path defaults to `services.yaml`. If `--graph` is omitted, the
first graph declared in the YAML file runs. `--scope` is an alias for `--graph`.
Normal progress is written to standard output; warnings and errors are written to
standard error with Rich formatting.

## Local development

```bash
uv sync --locked --all-extras --dev
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy .
```

## Container image workflow

The project includes a multi-stage Dockerfile suitable for the GitHub Actions pipeline.
The workflow builds and pushes the image to GHCR for pushes to the default branch and
version tags.
