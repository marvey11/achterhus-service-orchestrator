from __future__ import annotations

from support import (
    TelemetryReporter,
    _DummyResponse,
    _DummySession,
    requests,
)


def test_telemetry_reporter_submits_runs_events_and_status_updates() -> None:
    session = _DummySession()
    reporter = TelemetryReporter(
        api_url="http://telemetry.local",
        session=session,
    )

    assert (
        reporter.register_run("worker", "11111111-1111-4111-8111-111111111111") is True
    )
    assert (
        reporter.update_status("11111111-1111-4111-8111-111111111111", "STARTING")
        is True
    )
    assert (
        reporter.record_event("11111111-1111-4111-8111-111111111111", "checkpoint")
        is True
    )
    assert session.calls[0][0] == "POST"
    assert session.calls[1][0] == "PATCH"
    assert session.calls[2][0] == "POST"


def test_telemetry_reporter_handles_failure() -> None:
    class _BrokenSession:
        def get(self, *args: object, **kwargs: object) -> _DummyResponse:
            _ = (args, kwargs)
            raise requests.RequestException("boom")

        def post(self, *args: object, **kwargs: object) -> _DummyResponse:
            _ = (args, kwargs)
            raise requests.RequestException("boom")

        def patch(self, *args: object, **kwargs: object) -> _DummyResponse:
            _ = (args, kwargs)
            raise requests.RequestException("boom")

    reporter = TelemetryReporter(
        api_url="http://telemetry.local",
        session=_BrokenSession(),
    )
    assert reporter.register_run("app", "11111111-1111-4111-8111-111111111111") is False
    assert (
        reporter.update_status("11111111-1111-4111-8111-111111111111", "RUNNING")
        is False
    )
