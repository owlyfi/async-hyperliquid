import logging
from types import TracebackType
from typing import Any
from traceback import TracebackException

from aiohttp import ClientSession

from async_hyperliquid.utils.types import Endpoint
from async_hyperliquid.utils.constants import MAINNET_API_URL

logger = logging.getLogger(__name__)
_REDACTED = "<redacted>"
_SENSITIVE_PAYLOAD_KEYS = frozenset({"signature", "signatures"})


def _redact_payload(payload: Any) -> Any:
    if isinstance(payload, dict):
        redacted: dict[str, Any] = {}
        for key, value in payload.items():
            if key in _SENSITIVE_PAYLOAD_KEYS:
                redacted[key] = _REDACTED
            elif key == "action" and isinstance(value, dict):
                redacted[key] = {
                    "type": value.get("type"),
                    "keys": sorted(value.keys()),
                }
            else:
                redacted[key] = _redact_payload(value)
        return redacted

    if isinstance(payload, list):
        return [_redact_payload(item) for item in payload]

    return payload


class AsyncAPI:
    def __init__(
        self,
        endpoint: Endpoint,
        base_url: str | None = None,
        session: ClientSession = None,  # type: ignore
        *,
        owns_session: bool = True,
    ):
        self.endpoint = endpoint
        self.base_url = (base_url or MAINNET_API_URL).rstrip("/")
        self.session = session
        self._owns_session = owns_session
        self._request_url = f"{self.base_url}/{self.endpoint.value}"

    # for async with AsyncAPI() as api usage
    async def __aenter__(self) -> "AsyncAPI":
        return self

    async def __aexit__(
        self, exc_type: Exception, exc_val: TracebackException, traceback: TracebackType
    ) -> None:
        await self.close()

    async def close(self) -> None:
        if (
            getattr(self, "_owns_session", True)
            and self.session
            and not self.session.closed
        ):
            await self.session.close()

    async def post(self, payload: dict | None = None) -> Any:
        if self.session is None:
            raise RuntimeError("ClientSession is not initialized")

        payload = payload or {}
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("POST %s %s", self._request_url, _redact_payload(payload))

        async with self.session.post(self._request_url, json=payload) as resp:
            resp.raise_for_status()
            try:
                return await resp.json()
            except Exception as e:
                logger.error(
                    "Error parsing JSON response from %s: %s", self._request_url, e
                )
                return await resp.text()
