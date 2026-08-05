import asyncio
import warnings
from typing import Never

import pytest

from async_hyperliquid import InfoClient
from async_hyperliquid.errors import HttpError
from async_hyperliquid.types import JsonObject, JsonValue, Network


class IntegrationInfoClient(InfoClient):
    __slots__ = ("_network",)

    def __init__(self, network: Network) -> None:
        super().__init__(network=network)
        self._network = network

    @property
    def network(self) -> Network:
        return self._network

    async def _post(self, payload: JsonObject) -> JsonValue:
        try:
            return await super()._post(payload)
        except HttpError as error:
            if error.status != 429:
                self._handle_unavailable(error, payload)
            await asyncio.sleep(60)
        try:
            return await super()._post(payload)
        except HttpError as error:
            if error.status == 429:
                pytest.skip("Info API remained rate limited after retry")  # type: ignore
            self._handle_unavailable(error, payload)

    def _handle_unavailable(self, error: HttpError, payload: JsonObject) -> Never:
        status = error.status
        if (
            self._network is Network.TESTNET
            and status is not None
            and 500 <= status < 600
        ):
            request_type = payload.get("type", "unknown")
            warnings.warn(
                f"TESTNET {request_type} returned HTTP {status}",
                RuntimeWarning,
                stacklevel=2,
            )
            skip_reason = f"TESTNET {request_type} is temporarily unavailable"
            pytest.skip(skip_reason)  # type: ignore
        raise error
