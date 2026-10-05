from __future__ import annotations

from support import (
    DockerImageManager,
    Orchestrator,
    OrchestratorConfig,
    Path,
    ServiceConfig,
    TelemetryReporter,
    _DummyImageManager,
    _DummySession,
    _DummyWatchguard,
    pytest,
    sys,
)


def test_orchestrator_executes_each_service_in_dependency_order() -> None:
    config = OrchestratorConfig(
        services={
            "database": ServiceConfig(image="ghcr.io/example/db:latest"),
            "api": ServiceConfig(image="ghcr.io/example/api:latest"),
        },
        graphs={"nightly": {"database": set(), "api": {"database"}}},
    )

    orchestrator = Orchestrator(
        config,
        image_manager=_DummyImageManager(),
        watchguard=_DummyWatchguard(),
    )
    batches = orchestrator.run()

    assert [batch.services for batch in batches] == [("database",), ("api",)]


def test_orchestrator_registers_run_before_starting_container() -> None:
    config = OrchestratorConfig(
        services={"worker": ServiceConfig(image="ghcr.io/example/worker:latest")},
        graphs={"nightly": {"worker": set()}},
    )
    session = _DummySession()
    watchguard = _DummyWatchguard()
    orchestrator = Orchestrator(
        config,
        image_manager=_DummyImageManager(),
        watchguard=watchguard,
        telemetry_reporter=TelemetryReporter(
            api_url="http://telemetry.local",
            session=session,
        ),
    )

    orchestrator.run()

    registered_run_id = session.calls[0][2]["json"]["run_id"]
    assert session.calls[0][0] == "POST"
    assert session.calls[0][1] == "http://telemetry.local/api/v1/runs"
    assert registered_run_id == watchguard.calls[0][1]
    assert [call[2]["json"]["status"] for call in session.calls[1:]] == [
        "IMAGE_PULLING",
        "STARTING",
    ]


def test_start_cli_and_image_reference_parsing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_path = tmp_path / "services.yaml"
    config_path.write_text(
        """
services:
  app:
    image: ghcr.io/example/app:latest
graphs:
  nightly:
    app: []
  weekly:
    app: []
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setattr(sys, "argv", ["prog", str(config_path), "--graph", "weekly"])

    import orchestrator.main as orchestrator_main

    selected_graphs: list[str | None] = []

    class _DummyOrchestrator:
        def __init__(self, config: object, *, graph: str | None = None) -> None:
            self.config = config
            selected_graphs.append(graph)

        def run(self) -> None:
            return None

    monkeypatch.setattr(orchestrator_main, "Orchestrator", _DummyOrchestrator)
    orchestrator_main.start()
    assert selected_graphs == ["weekly"]
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
    assert ServiceConfig.model_validate(
        {
            "image": "ghcr.io/example/app:latest",
            "environment": None,
            "volumes": "host:/data",
        }
    ).volumes == ["host:/data"]
