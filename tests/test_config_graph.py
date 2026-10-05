from __future__ import annotations

from support import (
    ExecutionBatch,
    OrchestratorConfig,
    Path,
    ServiceConfig,
    ServiceDependencyGraph,
    pytest,
)


def test_yaml_selects_named_graphs_with_shared_services(tmp_path: Path) -> None:
    config_path = tmp_path / "services.yaml"
    config_path.write_text(
        """
services:
  service_a:
    image: example/a:latest
  service_b:
    image: example/b:latest
  service_c:
    image: example/c:latest
  backup:
    image: example/backup:latest
graphs:
  nightly:
    service_a: []
    service_b: []
    backup: [service_a, service_b]
  weekly:
    service_a: []
    service_b: []
    service_c: []
    backup: [service_a, service_b, service_c]
""".strip(),
        encoding="utf-8",
    )

    config = OrchestratorConfig.from_yaml_file(config_path)
    assert config.default_graph_name == "nightly"
    nightly = config.select_graph()
    weekly = config.select_graph("weekly")
    assert set(nightly.services) == {"service_a", "service_b", "backup"}
    assert set(weekly.services) == {"service_a", "service_b", "service_c", "backup"}

    graph = ServiceDependencyGraph(weekly)
    assert graph.get_execution_batches() == [
        ExecutionBatch(services=("service_a", "service_b", "service_c")),
        ExecutionBatch(services=("backup",)),
    ]


def test_graph_rejects_unknown_services_and_dependencies() -> None:
    with pytest.raises(ValueError, match="undefined services"):
        OrchestratorConfig.model_validate(
            {
                "services": {"api": {"image": "example/api:latest"}},
                "graphs": {"nightly": {"missing": []}},
            }
        )

    with pytest.raises(ValueError, match="not included in that graph"):
        OrchestratorConfig.model_validate(
            {
                "services": {"api": {"image": "example/api:latest"}},
                "graphs": {"nightly": {"api": ["database"]}},
            }
        )


def test_config_requires_graphs_and_rejects_unknown_graph_name() -> None:
    with pytest.raises(ValueError, match="at least one graph"):
        OrchestratorConfig.model_validate(
            {"services": {"api": {"image": "example/api:latest"}}, "graphs": {}}
        )

    config = OrchestratorConfig.model_validate(
        {
            "services": {"api": {"image": "example/api:latest"}},
            "graphs": {"nightly": {"api": []}},
        }
    )
    with pytest.raises(ValueError, match="Unknown graph 'weekly'"):
        config.select_graph("weekly")


def test_service_config_validation_and_yaml_errors(tmp_path: Path) -> None:
    with pytest.raises(TypeError, match="environment"):
        ServiceConfig.model_validate({"image": "example/app:latest", "environment": 7})

    with pytest.raises(TypeError, match="volumes"):
        ServiceConfig.model_validate({"image": "example/app:latest", "volumes": 7})

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


def test_service_config_normalises_values() -> None:
    config = ServiceConfig.model_validate(
        {
            "image": "example/app:latest",
            "environment": {"DEBUG": "1", "PORT": 8080},
            "volumes": "data:/data",
            "timeout_seconds": 42,
        }
    )
    assert config.environment == {"DEBUG": "1", "PORT": "8080"}
    assert config.volumes == ["data:/data"]
    assert config.timeout_seconds == 42


def test_graph_handles_failure_and_cycle_detection() -> None:
    config = OrchestratorConfig(
        services={
            "database": ServiceConfig(image="example/db:latest"),
            "api": ServiceConfig(image="example/api:latest"),
        },
        graphs={"default": {"database": set(), "api": {"database"}}},
    )
    graph = ServiceDependencyGraph(config.select_graph())
    graph.get_ready_services()
    graph.mark_failed("database")
    assert graph.statuses["database"].name == "FAILED"
    assert graph.get_execution_batches() == [
        ExecutionBatch(services=("database",)),
        ExecutionBatch(services=("api",)),
    ]

    cycle_config = OrchestratorConfig(
        services={
            "a": ServiceConfig(image="example/a:latest"),
            "b": ServiceConfig(image="example/b:latest"),
        },
        graphs={"cycle": {"a": {"b"}, "b": {"a"}}},
    )
    with pytest.raises(Exception):
        ServiceDependencyGraph(cycle_config.select_graph("cycle"))
