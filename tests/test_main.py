from __future__ import annotations

import sys
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest
import requests

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

from orchestrator.main import (
    ContainerWatchguard,
    DockerImageManager,
    ExecutionBatch,
    Orchestrator,
    OrchestratorConfig,
    ServiceConfig,
    ServiceDependencyGraph,
    TelemetryReporter,
    WatchguardResult,
)


class _DummyResponse:
    def __init__(
        self,
        *,
        status_code: int = 200,
        headers: dict[str, str] | None = None,
        payload: dict[str, object] | None = None,
    ) -> None:
        self.status_code = status_code
        self.headers = headers or {}
        self._payload = payload or {}

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return self._payload


class _DummySession:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        timeout: float = 5.0,
        **kwargs: object,
    ) -> _DummyResponse:
        _ = (url, headers, timeout, kwargs)
        self.calls.append(
            ("GET", url, {"headers": dict(headers or {}), "timeout": timeout})
        )
        return _DummyResponse(headers={"Docker-Content-Digest": "sha256:abc123"})

    def post(
        self,
        url: str,
        *,
        json: Mapping[str, object] | None = None,
        timeout: float = 5.0,
        **kwargs: object,
    ) -> _DummyResponse:
        _ = (url, json, timeout, kwargs)
        self.calls.append(("POST", url, {"json": dict(json or {}), "timeout": timeout}))
        return _DummyResponse()

    def patch(
        self,
        url: str,
        *,
        json: Mapping[str, object] | None = None,
        timeout: float = 5.0,
        **kwargs: object,
    ) -> _DummyResponse:
        _ = (url, json, timeout, kwargs)
        self.calls.append(
            ("PATCH", url, {"json": dict(json or {}), "timeout": timeout})
        )
        return _DummyResponse()


class _DummyDigestSession:
    def __init__(
        self,
        *,
        status_code: int = 200,
        headers: dict[str, str] | None = None,
        payload: dict[str, object] | None = None,
    ) -> None:
        self.status_code = status_code
        self.headers = headers or {}
        self.payload = payload or {}

    def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        timeout: float = 5.0,
        **kwargs: object,
    ) -> _DummyResponse:
        _ = (url, headers, timeout, kwargs)
        return _DummyResponse(
            status_code=self.status_code,
            headers=self.headers,
            payload=self.payload,
        )

    def post(
        self,
        url: str,
        *,
        json: Mapping[str, object] | None = None,
        timeout: float = 5.0,
        **kwargs: object,
    ) -> _DummyResponse:
        _ = (url, json, timeout, kwargs)
        return _DummyResponse(status_code=self.status_code, payload=self.payload)

    def patch(
        self,
        url: str,
        *,
        json: Mapping[str, object] | None = None,
        timeout: float = 5.0,
        **kwargs: object,
    ) -> _DummyResponse:
        _ = (url, json, timeout, kwargs)
        return _DummyResponse(status_code=self.status_code, payload=self.payload)


class _DummyImage:
    def __init__(self, digests: list[str] | None = None) -> None:
        self.attrs = {"RepoDigests": digests or []}


class _DummyDockerImages:
    def __init__(self, image_digests: list[str] | None = None) -> None:
        self._image_digests = image_digests or []
        self.pulled: list[str] = []

    def get(self, image_name: str) -> _DummyImage:
        _ = image_name
        return _DummyImage(self._image_digests)

    def pull(self, image_name: str) -> None:
        self.pulled.append(image_name)


class _DummyDockerClient:
    def __init__(self, *, image_digests: list[str] | None = None) -> None:
        self.images = _DummyDockerImages(image_digests)
        self.containers = self
        self.run_calls: list[dict[str, object]] = []

    def run(self, **kwargs: object) -> _DummyContainer:
        _ = kwargs
        self.run_calls.append(kwargs)
        return _DummyContainer()


class _DummyImageManager:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def ensure_image_current(self, image_name: str) -> bool:
        self.calls.append(image_name)
        return True


class _DummyWatchguard:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def run_container(
        self,
        service_name: str,
        service: ServiceConfig,
        *,
        run_id: str,
        environment: Mapping[str, str] | None = None,
        network: str | None = None,
    ) -> WatchguardResult:
        _ = (service, environment, network)
        self.calls.append((service_name, run_id))
        return WatchguardResult(
            container_id="abc123",
            exit_code=0,
            timed_out=False,
            status="exited",
        )


class _DummyContainer:
    def __init__(self) -> None:
        self.id = "deadbeef"
        self.status = "running"
        self.attrs: dict[str, Any] = {"State": {"ExitCode": 0, "OOMKilled": False}}
        self.stopped = False

    def reload(self) -> None:
        if self.stopped:
            self.status = "exited"
            self.attrs["State"] = {"ExitCode": 137, "OOMKilled": False}

    def stop(self, timeout: int = 5) -> None:
        _ = timeout
        self.stopped = True
        self.status = "exited"
        self.attrs["State"] = {"ExitCode": 137, "OOMKilled": False}

    def remove(self, force: bool = False) -> None:
        _ = force
        return None


def test_service_config_supports_yaml_and_topological_order(tmp_path: Path) -> None:
    config_path = tmp_path / "services.yaml"
    config_path.write_text(
        """
services:
  database:
    image: ghcr.io/example/postgres:latest
  api:
    image: ghcr.io/example/api:latest
    depends_on:
      - database
""".strip(),
        encoding="utf-8",
    )

    config = OrchestratorConfig.from_yaml_file(config_path)
    graph = ServiceDependencyGraph(config)

    assert graph.get_ready_services() == ("database",)
    graph.mark_completed("database")
    assert graph.get_ready_services() == ("api",)


def test_yaml_rejects_undefined_dependencies(tmp_path: Path) -> None:
    config_path = tmp_path / "services.yaml"
    config_path.write_text(
        """
services:
  api:
    image: ghcr.io/example/api:latest
    depends_on:
      - missing-service
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="undefined dependencies"):
        OrchestratorConfig.from_yaml_file(config_path)


def test_telemetry_reporter_submits_runs_events_and_status_updates() -> None:
    session = _DummySession()
    reporter = TelemetryReporter(
        api_url="http://telemetry.local",
        session=session,
    )

    assert (
        reporter.register_run("worker", "11111111-1111-4111-8111-111111111111") is True
    )
    assert (
        reporter.update_status("11111111-1111-4111-8111-111111111111", "STARTING")
        is True
    )
    assert (
        reporter.record_event("11111111-1111-4111-8111-111111111111", "checkpoint")
        is True
    )
    assert session.calls[0][0] == "POST"
    assert session.calls[1][0] == "PATCH"
    assert session.calls[2][0] == "POST"


def test_image_manager_pulls_when_remote_digest_changes() -> None:
    docker_client = _DummyDockerClient(image_digests=["ghcr.io/example/app@sha256:old"])
    session = _DummySession()
    image_manager = DockerImageManager(docker_client=docker_client, session=session)

    assert image_manager.ensure_image_current("ghcr.io/example/app:latest") is True
    assert docker_client.images.pulled == ["ghcr.io/example/app:latest"]

    docker_client.images = _DummyDockerImages(["ghcr.io/example/app@sha256:abc123"])
    assert image_manager.ensure_image_current("ghcr.io/example/app:latest") is False


def test_image_manager_handles_registry_variants_and_missing_data() -> None:
    with pytest.raises(ValueError):
        DockerImageManager.parse_image_reference("")

    assert DockerImageManager.parse_image_reference("ghcr.io/example/app:1.2.3") == (
        "ghcr.io",
        "example/app",
        "1.2.3",
    )
    assert DockerImageManager.parse_image_reference("localhost:5000/service") == (
        "localhost:5000",
        "service",
        "latest",
    )

    docker_client = _DummyDockerClient(image_digests=["ghcr.io/example/app@sha256:old"])
    manager = DockerImageManager(
        docker_client=docker_client,
        session=_DummyDigestSession(
            payload={"digest": "sha256:payload"},
        ),
    )
    assert manager.get_remote_manifest_digest("ghcr.io/example/app:latest") == (
        "sha256:payload"
    )
    assert manager.ensure_image_current("ghcr.io/example/app:latest") is True
    assert docker_client.images.pulled == ["ghcr.io/example/app:latest"]

    empty_session = _DummyDigestSession(status_code=404)
    empty_manager = DockerImageManager(
        docker_client=docker_client,
        session=empty_session,
    )
    digest = empty_manager.get_remote_manifest_digest("ghcr.io/example/app:latest")
    assert digest is None


def test_watchguard_stops_timed_out_container() -> None:
    docker_client = _DummyDockerClient()
    session = _DummySession()
    telemetry = TelemetryReporter(api_url="http://telemetry.local", session=session)
    watchguard = ContainerWatchguard(
        docker_client=docker_client,
        timeout_seconds=0.01,
        telemetry_reporter=telemetry,
    )

    result = watchguard.run_container(
        "worker",
        ServiceConfig(image="ghcr.io/example/worker:latest"),
        run_id="11111111-1111-4111-8111-111111111111",
    )

    assert result.timed_out is True
    assert result.container_id == "deadbeef"


def test_watchguard_reports_oom_and_timeout_statuses() -> None:
    class _OOMContainer(_DummyContainer):
        def reload(self) -> None:
            self.status = "exited"
            self.attrs = {"State": {"ExitCode": 137, "OOMKilled": True}}

    class _TimeoutContainer(_DummyContainer):
        def reload(self) -> None:
            self.status = "running"
            self.attrs = {"State": {"ExitCode": 0, "OOMKilled": False}}

    telemetry = TelemetryReporter(
        api_url="http://telemetry.local",
        session=_DummySession(),
    )

    def _run_oom_container(**_kwargs: object) -> _OOMContainer:
        _ = _kwargs
        return _OOMContainer()

    oom_watchguard = ContainerWatchguard(
        docker_client=SimpleNamespace(
            containers=SimpleNamespace(run=_run_oom_container)
        ),
        timeout_seconds=30,
        telemetry_reporter=telemetry,
    )
    oom_result = oom_watchguard.run_container(
        "oom-worker",
        ServiceConfig(
            image="ghcr.io/example/oom:latest",
            command="echo boom",
            working_dir="workspace",
            network="bridge",
            volumes=["workspace:/workspace"],
        ),
        run_id="11111111-1111-4111-8111-111111111112",
    )
    assert oom_result.timed_out is False
    assert oom_result.exit_code == 137
    assert oom_result.status == "exited"

    def _run_timeout_container(**_kwargs: object) -> _TimeoutContainer:
        _ = _kwargs
        return _TimeoutContainer()

    timeout_watchguard = ContainerWatchguard(
        docker_client=SimpleNamespace(
            containers=SimpleNamespace(run=_run_timeout_container)
        ),
        timeout_seconds=0,
        telemetry_reporter=telemetry,
    )
    timeout_result = timeout_watchguard.run_container(
        "slow-worker",
        ServiceConfig(
            image="ghcr.io/example/slow:latest",
            command=["python", "-m", "worker"],
            timeout_seconds=0,
        ),
        run_id="11111111-1111-4111-8111-111111111113",
    )
    assert timeout_result.timed_out is True
    assert timeout_result.exit_code == 137


def test_orchestrator_executes_each_service_in_dependency_order() -> None:
    config = OrchestratorConfig(
        services={
            "database": ServiceConfig(image="ghcr.io/example/db:latest"),
            "api": ServiceConfig(
                image="ghcr.io/example/api:latest",
                depends_on={"database"},
            ),
        }
    )

    orchestrator = Orchestrator(
        config,
        image_manager=_DummyImageManager(),
        watchguard=_DummyWatchguard(),
    )
    batches = orchestrator.run()

    assert [batch.services for batch in batches] == [("database",), ("api",)]


def test_service_config_validation_and_yaml_errors(tmp_path: Path) -> None:
    with pytest.raises(TypeError, match="depends_on"):
        ServiceConfig.model_validate(
            {
                "image": "ghcr.io/example/app:latest",
                "depends_on": object(),
            }
        )

    with pytest.raises(TypeError, match="environment"):
        ServiceConfig.model_validate(
            {
                "image": "ghcr.io/example/app:latest",
                "environment": 7,
            }
        )

    with pytest.raises(TypeError, match="volumes"):
        ServiceConfig.model_validate(
            {
                "image": "ghcr.io/example/app:latest",
                "volumes": 7,
            }
        )

    missing = tmp_path / "missing.yaml"
    with pytest.raises(FileNotFoundError):
        OrchestratorConfig.from_yaml_file(missing)

    empty = tmp_path / "empty.yaml"
    empty.write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="empty"):
        OrchestratorConfig.from_yaml_file(empty)

    invalid_top = tmp_path / "invalid-top.yaml"
    invalid_top.write_text("- service\n- other\n", encoding="utf-8")
    with pytest.raises(ValueError, match="dictionary top-level"):
        OrchestratorConfig.from_yaml_file(invalid_top)

    invalid_services = tmp_path / "invalid-services.yaml"
    invalid_services.write_text("services: value\n", encoding="utf-8")
    with pytest.raises(ValueError, match=r"services.*mapping"):
        OrchestratorConfig.from_yaml_file(invalid_services)


def test_service_config_normalises_lists_and_values() -> None:
    config = ServiceConfig.model_validate(
        {
            "image": "ghcr.io/example/app:latest",
            "depends_on": ["database", "queue"],
            "environment": {"DEBUG": "1", "PORT": 8080},
            "volumes": ["data:/data"],
            "timeout_seconds": 42,
        }
    )

    assert config.depends_on == {"database", "queue"}
    assert config.environment == {"DEBUG": "1", "PORT": "8080"}
    assert config.volumes == ["data:/data"]
    assert config.timeout_seconds == 42


def test_graph_handles_failure_and_cycle_detection() -> None:
    config = OrchestratorConfig(
        services={
            "database": ServiceConfig(image="ghcr.io/example/db:latest"),
            "api": ServiceConfig(
                image="ghcr.io/example/api:latest",
                depends_on={"database"},
            ),
        }
    )
    graph = ServiceDependencyGraph(config)
    graph.get_ready_services()
    graph.mark_failed("database")
    assert graph.statuses["database"].name == "FAILED"
    assert graph.get_execution_batches() == [
        ExecutionBatch(services=("database",)),
        ExecutionBatch(services=("api",)),
    ]

    cycle_config = OrchestratorConfig(
        services={
            "a": ServiceConfig(image="ghcr.io/example/a:latest", depends_on={"b"}),
            "b": ServiceConfig(image="ghcr.io/example/b:latest", depends_on={"a"}),
        }
    )
    with pytest.raises(Exception):
        ServiceDependencyGraph(cycle_config)


def test_telemetry_reporter_handles_failure() -> None:
    class _BrokenSession:
        def get(self, *args: object, **kwargs: object) -> _DummyResponse:
            _ = (args, kwargs)
            raise requests.RequestException("boom")

        def post(self, *args: object, **kwargs: object) -> _DummyResponse:
            _ = (args, kwargs)
            raise requests.RequestException("boom")

        def patch(self, *args: object, **kwargs: object) -> _DummyResponse:
            _ = (args, kwargs)
            raise requests.RequestException("boom")

    reporter = TelemetryReporter(
        api_url="http://telemetry.local",
        session=_BrokenSession(),
    )
    assert reporter.register_run("app", "11111111-1111-4111-8111-111111111111") is False
    assert (
        reporter.update_status("11111111-1111-4111-8111-111111111111", "RUNNING")
        is False
    )


def test_start_cli_and_image_reference_parsing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_path = tmp_path / "services.yaml"
    config_path.write_text(
        """
services:
  app:
    image: ghcr.io/example/app:latest
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setattr(sys, "argv", ["prog", str(config_path)])

    import orchestrator.main as orchestrator_main

    class _DummyOrchestrator:
        def __init__(self, config: object) -> None:
            self.config = config

        def run(self) -> None:
            return None

    monkeypatch.setattr(orchestrator_main, "Orchestrator", _DummyOrchestrator)
    orchestrator_main.start()
    assert DockerImageManager.parse_image_reference("ghcr.io/example/app:1.2.3") == (
        "ghcr.io",
        "example/app",
        "1.2.3",
    )
    assert DockerImageManager.parse_image_reference("busybox") == (
        "docker.io",
        "busybox",
        "latest",
    )
    assert (
        ServiceConfig.model_validate(
            {
                "image": "ghcr.io/example/app:latest",
                "depends_on": None,
                "environment": None,
                "volumes": "host:/data",
            }
        ).depends_on
        == set()
    )
