from __future__ import annotations

import sys
from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import requests

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


__all__ = [
    "Any",
    "ContainerWatchguard",
    "DockerImageManager",
    "ExecutionBatch",
    "Mapping",
    "Orchestrator",
    "OrchestratorConfig",
    "Path",
    "ServiceConfig",
    "ServiceDependencyGraph",
    "SimpleNamespace",
    "TelemetryReporter",
    "WatchguardResult",
    "_DummyContainer",
    "_DummyDigestSession",
    "_DummyDockerClient",
    "_DummyDockerImages",
    "_DummyImage",
    "_DummyImageManager",
    "_DummyResponse",
    "_DummySession",
    "_DummyWatchguard",
    "pytest",
    "requests",
    "sys",
]
