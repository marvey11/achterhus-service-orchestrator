# AGENTS.md

`achterhus-service-orchestrator` is a Python application for orchestrating Dockerised services on a home server.

## Repository layout

- This is a Python 3.14+ project using the `src/` layout.
- Package code lives in `src/orchestrator/` and is the implementation boundary for the runtime.
- Tests live in `tests/` and use pytest.
- Dependencies and tool configuration are defined in `pyproject.toml`; `uv.lock` is committed.
- GitHub automation lives under `.github/workflows/` and should be kept consistent with the release and CI responsibilities described here.
- `pyproject.toml` is the project source of truth for Python version, dependency groups, Ruff settings, mypy and Pyright settings, pytest configuration, and coverage thresholds. If a configuration question arises, check `pyproject.toml` before relying on editor defaults.

## Package responsibilities

- `src/orchestrator/config.py`: YAML config parsing, validation, and graph selection.
- `src/orchestrator/graph.py`: service dependency graph, execution batches, and watchguard state transitions.
- `src/orchestrator/orchestrator.py`: orchestrates each graph and schedules service execution in dependency order.
- `src/orchestrator/docker_runtime.py`: image freshness checks plus container creation and supervision.
- `src/orchestrator/telemetry.py`: lifecycle reporting to the configured Telemetry API.
- `src/orchestrator/contracts.py`: domain contracts for telemetry payloads and run state transitions.
- `src/orchestrator/main.py`: Typer CLI entrypoint exposed as the `orchestrator` script.

## Development commands

Use `uv` from the repository root:

```bash
uv sync --locked --all-extras --dev
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy .
uv run pyright
```

Local workflow and Git hooks are installed with:

```bash
./scripts/bootstrap.sh
```

The bootstrap script installs the project dependencies and pre-commit hooks for both the standard checks and the pre-push suite.

## Development conventions

- Target Python 3.14 or newer.
- Add explicit annotations for functions, parameters, and return values.
- Prefer `typing.Annotated` for Typer command arguments and options when defining CLI metadata.
- Use Rich `Console` instances for CLI output. Use a stderr console for warnings and errors and a stdout console for normal output.
- Preserve command exit codes and user-visible output unless changing the CLI contract is part of the task.
- Raise exceptions with `from err` when converting an underlying error at a boundary, such as a CLI handler.
- Do not add comments that merely restate the code. Add a comment only when the reason for a non-obvious decision cannot be expressed clearly in the code.
- Keep the repository's automation honest: workflows and pre-commit hooks must reflect the actual project checks, not weakened alternatives.

## Validation workflow

Run the same checks that CI runs before submitting changes:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy .
uv run pyright
# run only tests
uv run pytest
# run tests and coverage
./scripts/run-coverage.sh
```

Use focused tests during development and the full suite before final submission.

## CI, release automation, and pre-commit

The authoritative CI pipeline is in [.github/workflows/ci.yml](.github/workflows/ci.yml). The repository also contains a release workflow in [.github/workflows/release.yml](.github/workflows/release.yml), which creates a GitHub release from a tag like `v1.2.8` and pushes matching `1.2.8`, `1.2`, and `1` container tags.

The project uses [.pre-commit-config.yaml](.pre-commit-config.yaml) for local quality hooks, including actionlint for GitHub workflow validation.

Do not weaken lint, type, test, or coverage settings to make a change pass. Fix the underlying code or add focused tests for the behavior being changed.
