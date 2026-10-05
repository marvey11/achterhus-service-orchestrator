from __future__ import annotations

import os
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator


class ServiceConfig(BaseModel):
    """Configuration definition for an individual Docker service."""

    image: str = Field(..., description="Docker image name/tag")
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


@dataclass(frozen=True, slots=True)
class GraphScope:
    """Service definitions and dependency edges selected for one graph."""

    name: str
    services: dict[str, ServiceConfig]
    dependencies: dict[str, set[str]]


class OrchestratorConfig(BaseModel):
    """Shared service definitions and named execution graphs."""

    services: dict[str, ServiceConfig] = Field(
        ..., description="Map of service name to service configuration"
    )
    graphs: dict[str, dict[str, set[str]]] = Field(
        ..., description="Map of graph name to service dependency mapping"
    )

    @field_validator("graphs", mode="before")
    @classmethod
    def _normalise_graphs(cls, value: object) -> object:
        if not isinstance(value, Mapping):
            raise TypeError(
                "graphs must be a mapping of graph names to service mappings"
            )
        normalized: dict[str, dict[str, set[str]]] = {}
        for graph_name, graph_value in value.items():
            if not isinstance(graph_value, Mapping):
                raise TypeError(f"graph '{graph_name}' must be a service mapping")
            dependencies: dict[str, set[str]] = {}
            for service_name, dependency_values in graph_value.items():
                if dependency_values is None:
                    dependencies[str(service_name)] = set()
                elif isinstance(dependency_values, str):
                    dependencies[str(service_name)] = {dependency_values}
                elif isinstance(dependency_values, (list, tuple, set, frozenset)):
                    items = cast("Iterable[object]", dependency_values)
                    dependencies[str(service_name)] = {str(item) for item in items}
                else:
                    raise TypeError(
                        f"dependencies for service '{service_name}' in graph "
                        f"'{graph_name}' must be a sequence of service names"
                    )
            normalized[str(graph_name)] = dependencies
        return normalized

    @model_validator(mode="after")
    def validate_graph_references(self) -> OrchestratorConfig:
        if not self.graphs:
            raise ValueError("at least one graph must be defined")
        service_names = set(self.services)
        for graph_name, graph in self.graphs.items():
            if not graph:
                raise ValueError(
                    f"graph '{graph_name}' must include at least one service"
                )
            graph_services = set(graph)
            unknown_services = graph_services - service_names
            if unknown_services:
                unknown = ", ".join(sorted(unknown_services))
                raise ValueError(
                    f"Graph '{graph_name}' references undefined services: {unknown}"
                )
            for service_name, dependencies in graph.items():
                unknown_dependencies = dependencies - graph_services
                if unknown_dependencies:
                    unknown = ", ".join(sorted(unknown_dependencies))
                    raise ValueError(
                        f"Service '{service_name}' in graph '{graph_name}' depends on "
                        f"services not included in that graph: {unknown}"
                    )
        return self

    @property
    def default_graph_name(self) -> str:
        return next(iter(self.graphs))

    def select_graph(self, name: str | None = None) -> GraphScope:
        graph_name = self.default_graph_name if name is None else name
        try:
            dependencies = self.graphs[graph_name]
        except KeyError as err:
            available = ", ".join(self.graphs)
            raise ValueError(
                f"Unknown graph '{graph_name}'. Available graphs: {available}"
            ) from err
        return GraphScope(
            name=graph_name,
            services={
                service_name: self.services[service_name]
                for service_name in dependencies
            },
            dependencies=dependencies,
        )

    @classmethod
    def from_yaml_file(cls, path: Path | str) -> OrchestratorConfig:
        file_path = Path(path)
        if not file_path.exists():
            raise FileNotFoundError(f"Configuration file not found: {file_path}")

        raw_text = file_path.read_text(encoding="utf-8")
        expanded_text = os.path.expandvars(raw_text)
        raw_data: object = yaml.safe_load(expanded_text)
        if raw_data is None:
            raise ValueError(f"YAML file {file_path} is empty")
        if not isinstance(raw_data, dict):
            raise ValueError(
                f"YAML content in {file_path} must be a dictionary top-level"
            )
        return cls.model_validate(raw_data)
