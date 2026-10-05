from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Mapping

    type JSONValue = (
        str | int | float | bool | list["JSONValue"] | dict[str, "JSONValue"] | None
    )


class ResponseLike(Protocol):
    status_code: int
    headers: dict[str, str]

    def raise_for_status(self) -> None: ...

    def json(self) -> dict[str, object]: ...


class SessionLike(Protocol):
    def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        timeout: float = 5.0,
        **kwargs: object,
    ) -> ResponseLike: ...

    def post(
        self,
        url: str,
        *,
        json: Mapping[str, object] | None = None,
        timeout: float = 5.0,
        **kwargs: object,
    ) -> ResponseLike: ...

    def patch(
        self,
        url: str,
        *,
        json: Mapping[str, object] | None = None,
        timeout: float = 5.0,
        **kwargs: object,
    ) -> ResponseLike: ...
