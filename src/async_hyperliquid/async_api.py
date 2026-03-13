import logging
from types import TracebackType
from typing import Any
from traceback import TracebackException

from aiohttp import ClientSession

from async_hyperliquid.utils.types import Endpoint
from async_hyperliquid.utils.constants import MAINNET_API_URL

logger = logging.getLogger(__name__)


class AsyncAPI:
    def __init__(
        self,
        endpoint: Endpoint,
        base_url: str | None = None,
        session: ClientSession = None,  # type: ignore
    ):
        self.endpoint = endpoint
        self.base_url = base_url or MAINNET_API_URL
        self.session = session

    # for async with AsyncAPI() as api usage
    async def __aenter__(self) -> "AsyncAPI":
        return self

    async def __aexit__(
        self, exc_type: Exception, exc_val: TracebackException, traceback: TracebackType
    ) -> None:
        await self.close()

    async def close(self) -> None:
        if self.session and not self.session.closed:
            await self.session.close()

    async def post(self, payload: dict | None = None) -> Any:
        payload = payload or {}
        req_path = f"{self.base_url}/{self.endpoint.value}"
        logger.debug(f"POST {req_path} {payload}")
        async with self.session.post(req_path, json=payload) as resp:
            resp.raise_for_status()
            try:
                return await resp.json()
            except Exception as e:
                logger.error(f"Error parsing JSON response: {e}")
                return await resp.text()
