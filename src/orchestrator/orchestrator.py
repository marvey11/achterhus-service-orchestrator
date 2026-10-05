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
    ) -> None:
        self.config = config
        self.graph = ServiceDependencyGraph(config)
        self.image_manager: ImageManagerLike = image_manager or DockerImageManager()
        self.watchguard: ContainerRunnerLike = watchguard or ContainerWatchguard()

    def run(self) -> list[ExecutionBatch]:
        batches: list[ExecutionBatch] = []
        while self.graph.is_active:
            ready = self.graph.get_ready_services()
            if not ready:
                break
            batches.append(ExecutionBatch(services=ready))
            for service_name in ready:
                service = self.config.services[service_name]
                self.image_manager.ensure_image_current(service.image)
                run_id = str(uuid.uuid4())
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
