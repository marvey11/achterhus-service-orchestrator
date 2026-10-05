from __future__ import annotations

from support import (
    ExecutionBatch,
    OrchestratorConfig,
    Path,
    ServiceConfig,
    ServiceDependencyGraph,
    pytest,
)


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
