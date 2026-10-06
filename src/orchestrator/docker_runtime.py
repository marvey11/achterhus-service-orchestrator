from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Protocol, cast

import docker
import requests

from .graph import WatchguardResult
from .telemetry import TelemetryReporter

if TYPE_CHECKING:
    from collections.abc import Mapping

    from .config import ServiceConfig
    from .contracts import JSONValue, SessionLike


logger = logging.getLogger(__name__)


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

                    if oom_killed or (exit_code is not None and exit_code != 0):
                        reported_status = "OOM_KILLED" if oom_killed else "FAILED"
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
