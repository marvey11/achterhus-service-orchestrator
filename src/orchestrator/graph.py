from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from graphlib import CycleError, TopologicalSorter
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

    from .config import GraphScope


class ExecutionStatus(Enum):
    PENDING = auto()
    RUNNING = auto()
    COMPLETED = auto()
    FAILED = auto()


@dataclass(frozen=True, slots=True)
class ExecutionBatch:
    """Represents a set of service names that can be safely run concurrently."""

    services: tuple[str, ...]


@dataclass(slots=True)
class WatchguardResult:
    """Container execution outcome observed by the watchguard."""

    container_id: str
    exit_code: int | None
    timed_out: bool
    status: str


class DependencyGraphError(Exception):
    """Base exception for dependency graph structural issues."""


class CyclicDependencyError(DependencyGraphError):
    """Raised when a circular dependency is detected in the graph."""


class ExecutionStateError(DependencyGraphError):
    """Raised when an invalid state transition is attempted in the runner."""


class ServiceDependencyGraph:
    """Manages service DAG lifecycle, execution state, and topological ordering."""

    def __init__(self, scope: GraphScope) -> None:
        self._graph = scope.dependencies
        service_names = scope.services
        self._sorter: TopologicalSorter[str] = TopologicalSorter(self._graph)
        self._statuses: dict[str, ExecutionStatus] = {
            name: ExecutionStatus.PENDING for name in service_names
        }

        try:
            self._sorter.prepare()
        except CycleError as err:
            cycle_nodes = " -> ".join(str(node) for node in err.args[1])
            raise CyclicDependencyError(
                f"Cyclic dependency detected among services: {cycle_nodes}"
            ) from err

    @property
    def is_active(self) -> bool:
        return self._sorter.is_active()

    @property
    def statuses(self) -> Mapping[str, ExecutionStatus]:
        return self._statuses

    def get_ready_services(self) -> tuple[str, ...]:
        ready_nodes = tuple(sorted(self._sorter.get_ready()))
        for service_name in ready_nodes:
            self._statuses[service_name] = ExecutionStatus.RUNNING
        return ready_nodes

    def mark_completed(self, service_name: str) -> None:
        if self._statuses.get(service_name) != ExecutionStatus.RUNNING:
            raise ExecutionStateError(
                f"Cannot complete service '{service_name}' because it is not "
                "currently RUNNING."
            )
        self._statuses[service_name] = ExecutionStatus.COMPLETED
        self._sorter.done(service_name)

    def mark_failed(self, service_name: str) -> None:
        if self._statuses.get(service_name) != ExecutionStatus.RUNNING:
            raise ExecutionStateError(
                f"Cannot fail service '{service_name}' because it is not "
                "currently RUNNING."
            )
        self._statuses[service_name] = ExecutionStatus.FAILED

    def get_execution_batches(self) -> list[ExecutionBatch]:
        batches: list[ExecutionBatch] = []
        temp_sorter: TopologicalSorter[str] = TopologicalSorter(self._graph)
        temp_sorter.prepare()

        while temp_sorter.is_active():
            ready = tuple(sorted(temp_sorter.get_ready()))
            if not ready:
                break
            batches.append(ExecutionBatch(services=ready))
            for node in ready:
                temp_sorter.done(node)

        return batches
