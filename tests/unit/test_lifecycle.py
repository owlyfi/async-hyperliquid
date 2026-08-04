import asyncio
from typing import cast

from aiohttp import ClientSession
import pytest

from async_hyperliquid._internal.http import _HttpTransport


def test_transport_constructor_creates_no_async_resource() -> None:
    transport = _HttpTransport()

    assert transport._session is None


async def test_transport_rejects_requests_before_open_and_cannot_reopen() -> None:
    transport = _HttpTransport()

    with pytest.raises(RuntimeError, match="not open"):
        await transport.post_json("https://example.test/info", {"type": "allMids"})

    await transport.close()
    await transport.close()

    with pytest.raises(RuntimeError, match="closed"):
        await transport.open()


async def test_owned_session_is_created_once_and_closed_once() -> None:
    transport = _HttpTransport()

    await transport.open()
    session = transport._session
    assert session is not None
    assert not session.closed

    await transport.open()
    assert transport._session is session

    await transport.close()
    await transport.close()
    assert session.closed


async def test_borrowed_session_is_never_closed() -> None:
    session = ClientSession()
    transport = _HttpTransport(session=session)

    try:
        await transport.open()
        await transport.open()
        await transport.close()
        await transport.close()

        assert not session.closed
    finally:
        await session.close()


async def test_open_rejects_an_already_closed_borrowed_session() -> None:
    session = ClientSession()
    await session.close()

    transport = _HttpTransport(session=session)

    with pytest.raises(RuntimeError, match="borrowed session is closed"):
        await transport.open()


async def test_async_context_manager_owns_the_complete_lifecycle() -> None:
    transport = _HttpTransport()

    async with transport as opened:
        assert opened is transport
        session = transport._session
        assert session is not None
        assert not session.closed

    assert session.closed
    with pytest.raises(RuntimeError, match="not open"):
        await transport.post_json("https://example.test/info", {"type": "allMids"})


class CancelOnceSession:
    closed = False

    def __init__(self) -> None:
        self.close_calls = 0

    async def close(self) -> None:
        self.close_calls += 1
        if self.close_calls == 1:
            raise asyncio.CancelledError
        self.closed = True


async def test_cancelled_close_can_be_retried_without_leaking_owned_session() -> None:
    session = CancelOnceSession()
    transport = _HttpTransport()
    transport._session = cast(ClientSession, session)
    transport._state = "open"

    with pytest.raises(asyncio.CancelledError):
        await transport.close()

    await transport.close()

    assert session.closed
    assert session.close_calls == 2
