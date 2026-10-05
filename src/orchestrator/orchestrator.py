from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from .docker_runtime import (
    ContainerRunnerLike,
    ContainerWatchguard,
    DockerImageManager,
    ImageManagerLike,
)
from .graph import ExecutionBatch, ServiceDependencyGraph
from .telemetry import TelemetryReporter

if TYPE_CHECKING:
    from .config import OrchestratorConfig


class Orchestrator:
    """Resolves a service DAG and delegates execution to the watchguard."""

    def __init__(
        self,
        config: OrchestratorConfig,
        *,
        image_manager: ImageManagerLike | None = None,
        watchguard: ContainerRunnerLike | None = None,
        graph: str | None = None,
        telemetry_reporter: TelemetryReporter | None = None,
    ) -> None:
        self.config = config
        self.scope = config.select_graph(graph)
        self.graph = ServiceDependencyGraph(self.scope)
        self.image_manager: ImageManagerLike = image_manager or DockerImageManager()
        self.telemetry_reporter = telemetry_reporter or TelemetryReporter()
        self.watchguard: ContainerRunnerLike = watchguard or ContainerWatchguard(
            telemetry_reporter=self.telemetry_reporter
        )

    def run(self) -> list[ExecutionBatch]:
        batches: list[ExecutionBatch] = []
        while self.graph.is_active:
            ready = self.graph.get_ready_services()
            if not ready:
                break
            batches.append(ExecutionBatch(services=ready))
            for service_name in ready:
                service = self.scope.services[service_name]
                run_id = str(uuid.uuid4())
                self.telemetry_reporter.register_run(service_name, run_id)
                if self.image_manager.ensure_image_current(service.image):
                    self.telemetry_reporter.update_status(run_id, "IMAGE_PULLING")
                self.telemetry_reporter.update_status(run_id, "STARTING")
                result = self.watchguard.run_container(
                    service_name,
                    service,
                    run_id=run_id,
                    environment={"SERVICE_NAME": service_name},
                )
                if result.timed_out or (
                    result.exit_code is not None and result.exit_code != 0
                ):
                    self.graph.mark_failed(service_name)
                else:
                    self.graph.mark_completed(service_name)
        return batches
