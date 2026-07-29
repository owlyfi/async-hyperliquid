from json import JSONDecodeError
import logging
import math
from time import monotonic
from types import TracebackType
from typing import Literal, Self, cast

from aiohttp import ClientError, ClientSession, ClientTimeout

from .errors import HttpError, ProtocolError
from .types import JsonObject, JsonValue


_DEFAULT_TIMEOUT = ClientTimeout(total=15, connect=3, sock_read=10)
_State = Literal["new", "open", "closed"]
_logger = logging.getLogger(__name__)


def _validate_timeout(timeout: ClientTimeout) -> None:
    for value in (timeout.total, timeout.connect, timeout.sock_read):
        if value is None or not math.isfinite(value) or value <= 0:
            raise ValueError("timeout budgets must be finite and greater than zero")


class _HttpTransport:
    def __init__(
        self,
        *,
        session: ClientSession | None = None,
        timeout: ClientTimeout | None = None,
    ) -> None:
        resolved_timeout = timeout or _DEFAULT_TIMEOUT
        _validate_timeout(resolved_timeout)

        self._session = session
        self._timeout = resolved_timeout
        self._owns_session = session is None
        self._state: _State = "new"

    async def open(self) -> None:
        if self._state == "closed":
            raise RuntimeError("transport is closed")
        if self._state == "open":
            return

        if self._session is None:
            self._session = ClientSession()
        elif self._session.closed:
            raise RuntimeError("borrowed session is closed")
        self._state = "open"

    async def close(self) -> None:
        if self._state == "closed":
            return

        session = self._session
        if self._owns_session and session is not None:
            await session.close()
        self._state = "closed"

    async def __aenter__(self) -> Self:
        await self.open()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.close()

    async def post_json(self, url: str, payload: JsonObject) -> JsonValue:
        if self._state != "open":
            raise RuntimeError("transport is not open")

        session = self._session
        if session is None or session.closed:
            raise RuntimeError("transport session is closed")

        started = monotonic() if _logger.isEnabledFor(logging.DEBUG) else None
        try:
            async with session.post(
                url, json=payload, timeout=self._timeout
            ) as response:
                if started is not None:
                    _logger.debug(
                        "HTTP response status=%d elapsed_ms=%.3f",
                        response.status,
                        (monotonic() - started) * 1_000,
                    )
                if not 200 <= response.status < 300:
                    raise HttpError(response.status)

                try:
                    decoded: object = await response.json(content_type=None)
                except (JSONDecodeError, UnicodeDecodeError):
                    raise ProtocolError("response is not valid JSON") from None
        except TimeoutError:
            raise
        except ClientError:
            raise HttpError from None

        return cast(JsonValue, decoded)
