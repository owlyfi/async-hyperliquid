import asyncio
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

from async_hyperliquid._async_hyperliquid.core import AsyncHyperliquidCore


@pytest.mark.asyncio
async def test_cancelled_metadata_loader_allows_waiter_to_retry() -> None:
    session = cast(Any, SimpleNamespace(closed=False, close=AsyncMock()))
    client = AsyncHyperliquidCore(
        address="0x1111111111111111111111111111111111111111",
        api_key="0x" + ("11" * 32),
        session=session,
    )
    first_started = asyncio.Event()
    attempts = 0

    async def refresh() -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            first_started.set()
            await asyncio.Future()
        client._metas_initialized = True

    client._refresh_metas = refresh  # type: ignore[method-assign]

    first = asyncio.create_task(client._ensure_metas_initialized())
    await first_started.wait()
    waiter = asyncio.create_task(client._ensure_metas_initialized())
    await asyncio.sleep(0)

    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first

    await waiter

    assert attempts == 2
