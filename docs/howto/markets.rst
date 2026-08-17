Work with market metadata
=========================

Trading workflows accept a market name, not a numeric asset ID. Use metadata
helpers instead of deriving protocol offsets in application code.

.. code-block:: python

   async with InfoClient() as info:
       await info.refresh_metadata()

       wire_name = await info.coin_name("HYPE/USDC")
       display_name = await info.coin_symbol(wire_name)
       asset = await info.asset_id(wire_name)
       size_decimals = await info.size_decimals(wire_name)

The first metadata lookup loads one immutable snapshot. Concurrent cold
lookups share that load. ``refresh_metadata()`` atomically replaces the last
complete snapshot; malformed or inconsistent metadata is rejected before it is
published.

Coin forms
----------

* Base perpetuals use names such as ``BTC``.
* HIP-3 perpetuals use a DEX prefix such as ``xyz:NVDA``.
* Spot pairs may have an internal canonical name such as ``@107`` and a
  metadata-derived display alias such as ``HYPE/USDC``.
* Outcome markets use ``#<encoding>``; ``+<encoding>`` is accepted as an alias.

``coin_name()`` returns the canonical wire name. ``coin_symbol()`` returns the
display symbol. ``spot_token_metadata()`` and ``token_id()`` resolve indexed
spot-token metadata: a spot pair or canonical coin normally maps to its base
token, while an indexed quote-token alias such as ``USDC`` can also resolve even
though it is not itself a tradable market. Perpetual market names do not resolve
as spot tokens. ``mark_price()`` reads venue context; ``mid_price()`` reads the
appropriate DEX mid-price response.

Batch constraints
-----------------

A placement batch may mix market and non-market orders and may span the base and
HIP-3 perpetual DEXes. A batch cannot mix perpetual markets with spot or outcome
markets. Market precision and builder-fee limits are resolved from the metadata
snapshot.

See :doc:`../coin-name-mapping` for the complete mapping and asset-space rules.
