# Achterhus Service Orchestrator

The Achterhus service orchestrator resolves Docker service dependency graphs, ensures the
necessary image is current, and executes the configured services in dependency order.

## Responsibilities

- Read and validate a YAML service configuration
- Resolve service execution order with `graphlib.TopologicalSorter`
- Pull or refresh an image only when the remote GHCR manifest differs
- Execute containers with their required environment, command and volumes
- Enforce an execution timeout through the container watchguard
- Report lifecycle events to the Telemetry API when `TELEMETRY_API_URL` is configured

## Configuration format

```yaml
services:
  postgres:
    image: ghcr.io/marvey11/achterhus-telemetry-api:latest
    environment:
      POSTGRES_DB: telemetry
      POSTGRES_USER: telemetry
      POSTGRES_PASSWORD: change-me
    volumes:
      - postgres-data:/var/lib/postgresql/data

  api:
    image: ghcr.io/marvey11/achterhus-telemetry-api:latest
    depends_on:
      - postgres
    environment:
      TELEMETRY_API_URL: http://telemetry-api:8000
    command: ["python", "-m", "telemetry.main"]
    timeout_seconds: 300
```

Each service entry may include:

- `image`
- `depends_on`
- `environment`
- `command`
- `volumes`
- `timeout_seconds`
- `working_dir`
- `network`

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
