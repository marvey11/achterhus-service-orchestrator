from __future__ import annotations

from support import (
    DockerImageManager,
    Orchestrator,
    OrchestratorConfig,
    Path,
    ServiceConfig,
    _DummyImageManager,
    _DummyWatchguard,
    pytest,
    sys,
)


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
