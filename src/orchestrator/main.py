from __future__ import annotations

import argparse
import logging
import os
import time
import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum, auto
from graphlib import CycleError, TopologicalSorter
from pathlib import Path
from typing import Any, Protocol, cast

import docker
import requests
import yaml
from pydantic import BaseModel, Field, field_validator

type JSONValue = (
    str | int | float | bool | list["JSONValue"] | dict[str, "JSONValue"] | None
)

logger = logging.getLogger(__name__)


class ResponseLike(Protocol):
    status_code: int
    headers: dict[str, str]

    def raise_for_status(self) -> None: ...

    def json(self) -> dict[str, object]: ...


class SessionLike(Protocol):
    def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        timeout: float = 5.0,
        **kwargs: object,
    ) -> ResponseLike: ...

    def post(
        self,
        url: str,
        *,
        json: Mapping[str, object] | None = None,
        timeout: float = 5.0,
        **kwargs: object,
    ) -> ResponseLike: ...

    def patch(
        self,
        url: str,
        *,
        json: Mapping[str, object] | None = None,
        timeout: float = 5.0,
        **kwargs: object,
    ) -> ResponseLike: ...


class ExecutionStatus(Enum):
    PENDING = auto()
    RUNNING = auto()
    COMPLETED = auto()
    FAILED = auto()


class ServiceConfig(BaseModel):
    """Configuration definition for an individual Docker service."""

    image: str = Field(..., description="Docker image name/tag")
    depends_on: set[str] = Field(
        default_factory=set,
        description="Set of service names this service directly depends on",
    )
    environment: dict[str, str] = Field(
        default_factory=dict,
        description="Environment variables to pass into the container",
    )
    command: str | list[str] | None = Field(
        default=None,
        description="Override command for the container execution",
    )
    volumes: list[str] = Field(
        default_factory=list,
        description="Docker bind mounts or named volumes for the container",
    )
    timeout_seconds: float | None = Field(
        default=None,
        description="Execution timeout in seconds for the container watchguard",
    )
    working_dir: str | None = Field(
        default=None,
        description="Working directory inside the container",
    )
    network: str | None = Field(
        default=None,
        description="Optional Docker network to attach the container to",
    )

    @field_validator("depends_on", mode="before")
    @classmethod
    def _normalise_dependencies(cls, value: object) -> set[str]:
        if value in (None, ""):
            return set()
        if isinstance(value, str):
            return {value}
        if isinstance(value, (set, frozenset, list, tuple)):
            iterable = cast("Iterable[object]", value)
            return {str(item) for item in iterable}
        raise TypeError(
            "depends_on must be a string, a set of strings, "
            "a sequence of strings, or null"
        )

    @field_validator("environment", mode="before")
    @classmethod
    def _normalise_environment(cls, value: object) -> dict[str, str]:
        if value is None:
            return {}
        if isinstance(value, Mapping):
            mapping = cast("Mapping[object, object]", value)
            return {str(key): str(val) for key, val in mapping.items()}
        raise TypeError("environment must be a mapping of variable names to values")

    @field_validator("volumes", mode="before")
    @classmethod
    def _normalise_volumes(cls, value: object) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [value]
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            iterable = cast("Iterable[object]", value)
            return [str(item) for item in iterable]
        raise TypeError("volumes must be a string, sequence of strings, or null")


class OrchestratorConfig(BaseModel):
    """Top-level pipeline configuration containing all service nodes."""

    services: dict[str, ServiceConfig] = Field(
        ..., description="Map of service name to service configuration"
    )

    @field_validator("services")
    @classmethod
    def validate_dependency_references(
        cls, services: dict[str, ServiceConfig]
    ) -> dict[str, ServiceConfig]:
        defined_services = set(services.keys())
        for service_name, config in services.items():
            missing_deps = config.depends_on - defined_services
            if missing_deps:
                missing_str = ", ".join(sorted(missing_deps))
                raise ValueError(
                    f"Service '{service_name}' references undefined dependencies: "
                    f"{missing_str}"
                )
        return services

    @classmethod
    def from_yaml_file(cls, path: Path | str) -> OrchestratorConfig:
        file_path = Path(path)
        if not file_path.exists():
            raise FileNotFoundError(f"Configuration file not found: {file_path}")

        raw_data: object = yaml.safe_load(file_path.read_text(encoding="utf-8"))
        if raw_data is None:
            raise ValueError(f"YAML file {file_path} is empty")

        if not isinstance(raw_data, dict):
            raise ValueError(
                f"YAML content in {file_path} must be a dictionary top-level"
            )

        raw_mapping = cast("dict[str, object]", raw_data)
        payload = raw_mapping.get("services", raw_mapping)
        if not isinstance(payload, dict):
            raise ValueError(
                "The service configuration must define a 'services' mapping or a "
                "top-level mapping keyed by service name"
            )

        return cls.model_validate({"services": payload})


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

    def __init__(self, config: OrchestratorConfig) -> None:
        self._config = config
        self._graph: dict[str, set[str]] = {
            name: cfg.depends_on for name, cfg in config.services.items()
        }
        self._sorter: TopologicalSorter[str] = TopologicalSorter(self._graph)
        self._statuses: dict[str, ExecutionStatus] = {
            name: ExecutionStatus.PENDING for name in config.services
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


class TelemetryReporter:
    """A thin wrapper around the Telemetry API status and event endpoints."""

    def __init__(
        self,
        api_url: str | None = None,
        *,
        timeout: float = 5.0,
        session: SessionLike | None = None,
    ) -> None:
        self.api_url = str(api_url or os.getenv("TELEMETRY_API_URL", "")).rstrip("/")
        self.timeout = timeout
        self._session: SessionLike = cast("SessionLike", session or requests.Session())

    @property
    def enabled(self) -> bool:
        return bool(self.api_url)

    def register_run(
        self,
        service_name: str,
        run_id: str,
        *,
        status: str = "SCHEDULED",
        source: str = "orchestrator",
        timestamp: datetime | None = None,
    ) -> bool:
        if not self.enabled:
            return False
        payload: dict[str, JSONValue] = {
            "service_name": service_name,
            "run_id": run_id,
            "status": status,
            "source": source,
            "timestamp": (timestamp or datetime.now(UTC)).isoformat(),
        }
        return self._request(
            method="post",
            path="/api/v1/runs",
            payload=payload,
        )

    def update_status(
        self,
        run_id: str,
        status: str,
        *,
        source: str = "orchestrator",
        error_details: Mapping[str, JSONValue] | None = None,
        metrics: Mapping[str, JSONValue] | None = None,
        logs_summary: str | None = None,
        timestamp: datetime | None = None,
    ) -> bool:
        if not self.enabled:
            return False
        payload: dict[str, JSONValue] = {
            "status": status,
            "source": source,
            "timestamp": (timestamp or datetime.now(UTC)).isoformat(),
        }
        if metrics:
            payload["metrics"] = dict(metrics)
        if logs_summary is not None:
            payload["logs_summary"] = logs_summary
        if error_details is not None:
            payload["error_details"] = dict(error_details)
        return self._request(
            method="patch",
            path=f"/api/v1/runs/{run_id}/status",
            payload=payload,
        )

    def record_event(
        self,
        run_id: str,
        event_type: str,
        details: Mapping[str, JSONValue] | None = None,
        *,
        source: str = "application",
        timestamp: datetime | None = None,
    ) -> bool:
        if not self.enabled:
            return False
        payload: dict[str, JSONValue] = {
            "event_type": event_type,
            "source": source,
            "timestamp": (timestamp or datetime.now(UTC)).isoformat(),
            "details": dict(details or {}),
        }
        return self._request(
            method="post",
            path=f"/api/v1/runs/{run_id}/events",
            payload=payload,
        )

    def _request(
        self, *, method: str, path: str, payload: dict[str, JSONValue]
    ) -> bool:
        try:
            func = getattr(self._session, method)
            response: ResponseLike = func(
                f"{self.api_url}{path}",
                json=payload,
                timeout=self.timeout,
            )
            response.raise_for_status()
            return True
        except requests.RequestException as exc:
            logger.warning("Telemetry API call failed: %s", exc)
            return False


class ImageManagerLike(Protocol):
    def ensure_image_current(self, image_name: str) -> bool: ...


class ContainerRunnerLike(Protocol):
    def run_container(
        self,
        service_name: str,
        service: ServiceConfig,
        *,
        run_id: str,
        environment: Mapping[str, str] | None = None,
        network: str | None = None,
    ) -> WatchguardResult: ...


class DockerImageManager:
    """Ensures a local container image is current with the remote registry digest."""

    def __init__(
        self,
        docker_client: object | None = None,
        *,
        session: SessionLike | None = None,
    ) -> None:
        self._docker: Any = docker_client or docker.from_env()
        self._session: SessionLike = cast("SessionLike", session or requests.Session())

    @staticmethod
    def _parse_image_reference(image_name: str) -> tuple[str, str, str]:
        candidate = image_name.strip()
        if not candidate:
            raise ValueError("Image name cannot be empty")

        tag = "latest"
        image_path = candidate
        if ":" in candidate.rsplit("/", 1)[-1]:
            image_path, tag = candidate.rsplit(":", 1)

        registry = "docker.io"
        repository = image_path
        if "/" in image_path:
            first_segment, remainder = image_path.split("/", 1)
            if (
                "." in first_segment
                or ":" in first_segment
                or first_segment == "localhost"
            ):
                registry = first_segment
                repository = remainder
            else:
                repository = image_path
        return registry, repository, tag

    def get_local_manifest_digest(self, image_name: str) -> str | None:
        try:
            repo_image = self._docker.images.get(image_name)
        except Exception:
            return None

        repo_attrs = cast("dict[str, object]", getattr(repo_image, "attrs", {}))
        repo_digests = repo_attrs.get("RepoDigests", [])
        if not isinstance(repo_digests, list):
            return None
        for repo_digest in cast("list[object]", repo_digests):
            if isinstance(repo_digest, str) and "@" in repo_digest:
                return repo_digest.split("@", 1)[1]
        return None

    def get_remote_manifest_digest(self, image_name: str) -> str | None:
        registry, repository, tag = self.parse_image_reference(image_name)
        url = f"https://{registry}/v2/{repository}/manifests/{tag}"
        response = self._session.get(
            url,
            headers={
                "Accept": (
                    "application/vnd.docker.distribution.manifest.v2+json, "
                    "application/vnd.docker.distribution.manifest.list.v2+json, "
                    "application/vnd.oci.image.manifest.v1+json, "
                    "application/vnd.oci.image.index.v1+json"
                )
            },
            timeout=10,
        )
        if response.status_code in {401, 404}:
            return None
        response.raise_for_status()
        digest = response.headers.get("Docker-Content-Digest")
        if digest:
            return digest
        payload = response.json()
        digest_value = payload.get("digest")
        if isinstance(digest_value, str):
            return digest_value
        return None

    @staticmethod
    def parse_image_reference(image_name: str) -> tuple[str, str, str]:
        return DockerImageManager._parse_image_reference(image_name)

    def ensure_image_current(self, image_name: str) -> bool:
        remote_digest = self.get_remote_manifest_digest(image_name)
        if remote_digest is None:
            return False
        local_digest = self.get_local_manifest_digest(image_name)
        if local_digest == remote_digest:
            return False
        self._docker.images.pull(image_name)
        return True


class ContainerWatchguard:
    """Runs containers and terminates them if they exceed the configured timeout."""

    def __init__(
        self,
        docker_client: object | None = None,
        *,
        timeout_seconds: float = 300,
        telemetry_reporter: TelemetryReporter | None = None,
    ) -> None:
        self._docker: Any = docker_client or docker.from_env()
        self.timeout_seconds = timeout_seconds
        self.telemetry_reporter = telemetry_reporter or TelemetryReporter()

    def run_container(
        self,
        service_name: str,
        service: ServiceConfig,
        *,
        run_id: str,
        environment: Mapping[str, str] | None = None,
        network: str | None = None,
    ) -> WatchguardResult:
        env = dict(service.environment)
        if environment:
            env.update(environment)
        env["SERVICE_RUN_ID"] = str(run_id)
        env["SERVICE_NAME"] = service_name

        command = service.command
        if isinstance(command, str):
            command = [command]

        container_kwargs: dict[str, object] = {
            "image": service.image,
            "command": command,
            "environment": env,
            "detach": True,
            "remove": False,
        }
        if service.volumes:
            container_kwargs["volumes"] = service.volumes
        if service.working_dir:
            container_kwargs["working_dir"] = service.working_dir
        if network or service.network:
            container_kwargs["network"] = network or service.network

        container = self._docker.containers.run(**container_kwargs)
        started_at = time.monotonic()
        timeout = service.timeout_seconds or self.timeout_seconds

        try:
            while True:
                container.reload()
                container_attrs = cast(
                    "dict[str, object]", getattr(container, "attrs", {})
                )
                state = container_attrs.get("State", {})
                if not isinstance(state, dict):
                    state = {}
                state_dict = cast("dict[str, object]", state)

                status = str(getattr(container, "status", "unknown")).lower()
                if status in {"exited", "dead"}:
                    exit_code_raw = state_dict.get("ExitCode")
                    exit_code: int | None
                    if isinstance(exit_code_raw, int):
                        exit_code = exit_code_raw
                    elif isinstance(exit_code_raw, str) and exit_code_raw.isdigit():
                        exit_code = int(exit_code_raw)
                    else:
                        exit_code = None
                    oom_killed = bool(state_dict.get("OOMKilled", False))

                    if oom_killed:
                        reported_status = "OOM_KILLED"
                    elif exit_code == 0 or exit_code is None:
                        reported_status = "SUCCESS"
                    else:
                        reported_status = "FAILED"

                    error_details: dict[str, JSONValue] | None = None
                    if exit_code is not None:
                        error_details = {"exit_code": exit_code}

                    self.telemetry_reporter.update_status(
                        run_id,
                        reported_status,
                        source="watchguard",
                        error_details=error_details,
                        timestamp=datetime.now(UTC),
                    )
                    return WatchguardResult(
                        container_id=str(getattr(container, "id", "")),
                        exit_code=exit_code,
                        timed_out=False,
                        status=status,
                    )

                if time.monotonic() - started_at > float(timeout):
                    try:
                        container.stop(timeout=5)
                    except Exception:
                        logger.warning(
                            "Failed to stop timed out container %s",
                            getattr(container, "id", "unknown"),
                        )
                    self.telemetry_reporter.update_status(
                        run_id,
                        "TIMEOUT",
                        source="watchguard",
                        timestamp=datetime.now(UTC),
                    )
                    return WatchguardResult(
                        container_id=str(getattr(container, "id", "")),
                        exit_code=137,
                        timed_out=True,
                        status=status,
                    )
                time.sleep(0.1)
        finally:
            try:
                container.remove(force=True)
            except Exception as exc:
                logger.debug(
                    "Failed to remove container %s after execution: %s",
                    getattr(container, "id", "unknown"),
                    exc,
                )


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


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Execute a Docker service DAG")
    parser.add_argument(
        "config",
        nargs="?",
        default="services.yaml",
        help="Path to the YAML service configuration file",
    )
    return parser


def start() -> None:
    args = _build_parser().parse_args()
    config = OrchestratorConfig.from_yaml_file(args.config)
    orchestrator = Orchestrator(config)
    orchestrator.run()


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
    "start",
]
