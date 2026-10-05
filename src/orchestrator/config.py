from __future__ import annotations

import os
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import cast

import yaml
from pydantic import BaseModel, Field, field_validator


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

        # Read raw YAML and expand $VAR / ${VAR} environment variables
        raw_text = file_path.read_text(encoding="utf-8")
        expanded_text = os.path.expandvars(raw_text)

        raw_data: object = yaml.safe_load(expanded_text)
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
