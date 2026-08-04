from __future__ import annotations

from types import TracebackType
from typing import TYPE_CHECKING, Self

from aiohttp import ClientSession, ClientTimeout

from ._http import _HttpTransport
from .info import InfoClient
from .types import Network

if TYPE_CHECKING:
    from .exchange import ExchangeClient


class AsyncHyperliquid:
    """Resource owner for bound Info and Exchange clients."""

    __slots__ = ("_exchange", "_info", "_transport")

    _transport: _HttpTransport
    _info: InfoClient
    _exchange: ExchangeClient

    def __init__(
        self,
        account_address: str,
        signing_key: str,
        *,
        vault_address: str | None = None,
        network: Network = Network.MAINNET,
        info_url: str | None = None,
        exchange_url: str | None = None,
        session: ClientSession | None = None,
        timeout: ClientTimeout | None = None,
        perp_dexes: tuple[str, ...] = ("",),
    ) -> None:
        from eth_account import Account

        try:
            account = Account.from_key(signing_key)
        except (TypeError, ValueError):
            raise ValueError("signing_key must be a 32-byte hex private key") from None

        from .exchange import ExchangeClient

        transport = _HttpTransport(session=session, timeout=timeout)
        self._transport = transport
        self._info = InfoClient._from_transport(
            transport, info_url=network.info_url if info_url is None else info_url
        )
        self._exchange = ExchangeClient(
            transport,
            self._info,
            account,
            account_address=account_address,
            vault_address=vault_address,
            network=network,
            exchange_url=exchange_url,
            perp_dexes=perp_dexes,
        )

    @property
    def info(self) -> InfoClient:
        return self._info

    @property
    def exchange(self) -> ExchangeClient:
        return self._exchange

    async def open(self) -> None:
        await self._transport.open()

    async def close(self) -> None:
        await self._transport.close()

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
