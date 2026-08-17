Query Info endpoints
====================

``InfoClient`` sends unsigned requests and can use mainnet, testnet, or an exact
custom Info URL. Prefer one long-lived context for a related set of reads.

Market data
-----------

The raw market methods preserve Hyperliquid response fields and numeric strings:

.. code-block:: python

   from async_hyperliquid import InfoClient
   from async_hyperliquid.types import CandleInterval


   async with InfoClient() as info:
       mids = await info.all_mids()
       book = await info.l2_book("BTC", n_sig_figs=5)
       candles = await info.candles(
           "BTC",
           CandleInterval.FIFTEEN_MINUTES,
           start_time_ms,
           end_time_ms,
       )

Use ``perp_meta()``, ``perp_meta_and_contexts()``, ``all_perp_metas()``,
``perp_dexes()``, ``spot_meta()``, and ``spot_meta_and_contexts()`` for venue
metadata and contexts. Funding and capacity reads include
``funding_history()``, ``predicted_fundings()``,
``perps_at_open_interest_cap()``, and ``perp_deploy_auction_status()``.

Account data
------------

Pass the portfolio owner, subaccount, or vault address explicitly. An API-wallet
address identifies a signing role and normally has no portfolio of its own.

.. code-block:: python

   async with InfoClient() as info:
       state = await info.account_state(account_address, dexs=("", "xyz"))
       orders = await info.open_orders(account_address, frontend=True)
       fills = await info.user_fills(account_address, aggregate_by_time=True)
       status = await info.order_status(account_address, order_id)

``account_state()`` combines spot state, base perpetual state, and the requested
HIP-3 DEX states. ``positions()`` flattens position entries from those DEXs.
Use ``perp_account_state()`` or ``spot_account_state()`` when only one venue is
needed.

Other account methods cover historical orders and TWAP fills; portfolio, fees,
rate limits, referrals, and ledger updates; subaccounts and vault equities;
staking summaries, history, rewards, and delegations; and account-abstraction
state. See :doc:`../reference/info-client` for exact signatures.

Time ranges
-----------

Timestamps are integer milliseconds. ``user_fills()`` requires ``start_time``
when ``end_time`` is supplied. Funding and non-funding ledger methods require a
start time and accept an optional end time.

Response handling
-----------------

Wire numeric fields such as prices, sizes, and balances remain strings in
detailed response types. Convert them with ``Decimal`` when exact arithmetic is
required. Info methods validate their expected top-level container or scalar,
but detailed nested fields are typed contracts rather than universally
runtime-validated data. Metadata and price helpers perform additional validation
for the fields they consume and raise ``ProtocolError`` for malformed values.
