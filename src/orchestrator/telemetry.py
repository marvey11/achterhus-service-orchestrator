from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

import requests

if TYPE_CHECKING:
    from collections.abc import Mapping

    from .contracts import JSONValue, ResponseLike, SessionLike

logger = logging.getLogger(__name__)


class TelemetryReporter:
    """A thin wrapper around the Telemetry API status and event endpoints."""

    def __init__(
        self,
        api_url: str | None = None,
        *,
        timeout: float = 5.0,
        session: SessionLike | None = None,
    ) -> None:
        self.api_url = str(api_url or os.getenv("TELEMETRY_API_URL", "")).rstrip("/")
        self.timeout = timeout
        self._session: SessionLike = cast("SessionLike", session or requests.Session())

    @property
    def enabled(self) -> bool:
        return bool(self.api_url)

    def register_run(
        self,
        service_name: str,
        run_id: str,
        *,
        status: str = "SCHEDULED",
        source: str = "orchestrator",
        timestamp: datetime | None = None,
    ) -> bool:
        if not self.enabled:
            return False
        payload: dict[str, JSONValue] = {
            "service_name": service_name,
            "run_id": run_id,
            "status": status,
            "source": source,
            "timestamp": (timestamp or datetime.now(UTC)).isoformat(),
        }
        return self._request(
            method="post",
            path="/api/v1/runs",
            payload=payload,
        )

    def update_status(
        self,
        run_id: str,
        status: str,
        *,
        source: str = "orchestrator",
        error_details: Mapping[str, JSONValue] | None = None,
        metrics: Mapping[str, JSONValue] | None = None,
        logs_summary: str | None = None,
        timestamp: datetime | None = None,
    ) -> bool:
        if not self.enabled:
            return False
        payload: dict[str, JSONValue] = {
            "status": status,
            "source": source,
            "timestamp": (timestamp or datetime.now(UTC)).isoformat(),
        }
        if metrics:
            payload["metrics"] = dict(metrics)
        if logs_summary is not None:
            payload["logs_summary"] = logs_summary
        if error_details is not None:
            payload["error_details"] = dict(error_details)
        return self._request(
            method="patch",
            path=f"/api/v1/runs/{run_id}/status",
            payload=payload,
        )

    def record_event(
        self,
        run_id: str,
        event_type: str,
        details: Mapping[str, JSONValue] | None = None,
        *,
        source: str = "application",
        timestamp: datetime | None = None,
    ) -> bool:
        if not self.enabled:
            return False
        payload: dict[str, JSONValue] = {
            "event_type": event_type,
            "source": source,
            "timestamp": (timestamp or datetime.now(UTC)).isoformat(),
            "details": dict(details or {}),
        }
        return self._request(
            method="post",
            path=f"/api/v1/runs/{run_id}/events",
            payload=payload,
        )

    def _request(
        self, *, method: str, path: str, payload: dict[str, JSONValue]
    ) -> bool:
        try:
            func = getattr(self._session, method)
            response: ResponseLike = func(
                f"{self.api_url}{path}",
                json=payload,
                timeout=self.timeout,
            )
            response.raise_for_status()
            return True
        except requests.RequestException as exc:
            logger.warning("Telemetry API call failed: %s", exc)
            return False
