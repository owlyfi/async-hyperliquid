from types import TracebackType
from typing import Self

from aiohttp import ClientSession, ClientTimeout
from eth_account import Account
from eth_utils import is_address, to_normalized_address

from ._http import _HttpTransport
from .exchange import ExchangeClient
from .info import InfoClient
from .types import Network


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
        network: Network = Network.MAINNET,
        info_url: str | None = None,
        exchange_url: str | None = None,
        session: ClientSession | None = None,
        timeout: ClientTimeout | None = None,
        perp_dexes: tuple[str, ...] = ("",),
    ) -> None:
        if not is_address(account_address):
            raise ValueError("account_address must be a 20-byte hex address")
        try:
            account = Account.from_key(signing_key)
        except (TypeError, ValueError):
            raise ValueError("signing_key must be a 32-byte hex private key") from None

        transport = _HttpTransport(session=session, timeout=timeout)
        self._transport = transport
        self._info = InfoClient._from_transport(
            transport, info_url=network.info_url if info_url is None else info_url
        )
        self._exchange = ExchangeClient._from_transport(
            transport,
            self._info,
            account,
            account_address=to_normalized_address(account_address),
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
