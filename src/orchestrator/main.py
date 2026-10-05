from __future__ import annotations

import logging
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.logging import RichHandler

from .config import OrchestratorConfig, ServiceConfig
from .docker_runtime import (
    ContainerRunnerLike,
    ContainerWatchguard,
    DockerImageManager,
    ImageManagerLike,
)
from .graph import (
    CyclicDependencyError,
    DependencyGraphError,
    ExecutionBatch,
    ExecutionStateError,
    ExecutionStatus,
    ServiceDependencyGraph,
    WatchguardResult,
)
from .orchestrator import Orchestrator
from .telemetry import TelemetryReporter

stdout_console = Console()
stderr_console = Console(stderr=True)
app = typer.Typer(help="Execute a Docker service dependency graph")


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(message)s",
        handlers=[RichHandler(console=stderr_console, rich_tracebacks=True)],
        force=True,
    )


@app.command()
def run(
    config: Annotated[
        Path,
        typer.Argument(help="Path to the YAML service configuration file"),
    ] = Path("services.yaml"),
) -> None:
    """Execute configured services in dependency order."""
    configure_logging()
    try:
        orchestrator_config = OrchestratorConfig.from_yaml_file(config)
        batches = Orchestrator(orchestrator_config).run() or []
    except Exception as err:
        stderr_console.print(f"[bold red]Error:[/bold red] {err}")
        raise typer.Exit(code=1) from err

    count = sum(len(batch.services) for batch in batches)
    stdout_console.print(f"Completed orchestration for {count} service(s).")


def start() -> None:
    app(standalone_mode=False)


__all__ = [
    "ContainerRunnerLike",
    "ContainerWatchguard",
    "CyclicDependencyError",
    "DependencyGraphError",
    "DockerImageManager",
    "ExecutionBatch",
    "ExecutionStateError",
    "ExecutionStatus",
    "ImageManagerLike",
    "Orchestrator",
    "OrchestratorConfig",
    "ServiceConfig",
    "ServiceDependencyGraph",
    "TelemetryReporter",
    "WatchguardResult",
    "app",
    "configure_logging",
    "run",
    "start",
]
