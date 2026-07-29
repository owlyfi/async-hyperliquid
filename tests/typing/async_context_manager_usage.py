from async_hyperliquid import AsyncHyperliquid


async def _uses_async_context_manager() -> None:
    # Static regression: `async with` should preserve the concrete client type.
    async with AsyncHyperliquid(
        account_address="0x" + "11" * 20, signing_key="0x" + "22" * 32
    ) as hl:
        typed_hl: AsyncHyperliquid = hl
        await typed_hl.info.all_mids()
