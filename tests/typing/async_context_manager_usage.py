from async_hyperliquid.async_hyperliquid import AsyncHyperliquid


async def _uses_async_context_manager() -> None:
    # Static regression: `async with` should preserve the concrete client type.
    async with AsyncHyperliquid(address="0x0", api_key="0x1") as hl:
        typed_hl: AsyncHyperliquid = hl
        await typed_hl.get_all_mids()
