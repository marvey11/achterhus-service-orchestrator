from __future__ import annotations

from support import (
    ContainerWatchguard,
    DockerImageManager,
    ServiceConfig,
    SimpleNamespace,
    TelemetryReporter,
    _DummyContainer,
    _DummyDigestSession,
    _DummyDockerClient,
    _DummyDockerImages,
    _DummySession,
    pytest,
)


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

    session = _DummySession()
    telemetry = TelemetryReporter(
        api_url="http://telemetry.local",
        session=session,
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
    assert session.calls[0][2]["json"]["status"] == "OOM_KILLED"

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


def test_watchguard_does_not_report_success_after_clean_exit() -> None:
    class _SuccessfulContainer(_DummyContainer):
        def reload(self) -> None:
            self.status = "exited"
            self.attrs = {"State": {"ExitCode": 0, "OOMKilled": False}}

    def _run_container(**_kwargs: object) -> _SuccessfulContainer:
        _ = _kwargs
        return _SuccessfulContainer()

    session = _DummySession()
    watchguard = ContainerWatchguard(
        docker_client=SimpleNamespace(containers=SimpleNamespace(run=_run_container)),
        telemetry_reporter=TelemetryReporter(
            api_url="http://telemetry.local",
            session=session,
        ),
    )

    result = watchguard.run_container(
        "worker",
        ServiceConfig(image="ghcr.io/example/worker:latest"),
        run_id="11111111-1111-4111-8111-111111111114",
    )

    assert result.exit_code == 0
    assert session.calls == []
