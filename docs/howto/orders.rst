Manage orders and positions
===========================

.. warning::

   Every placement, modification, cancellation, TWAP, leverage, margin, or close
   call is a real signed action on the selected network. Use testnet first,
   inspect the encoded intent, enforce application-level limits, and reconcile
   the result before retrying.

Order requests
--------------

Root-client order workflows resolve metadata and encode prices and sizes. A
``PlaceOrderRequest`` uses one vocabulary for single and batch operations:

.. code-block:: python

   from async_hyperliquid.types import (
       PlaceOrderRequest,
       TimeInForce,
       limit_order_type,
   )

   request: PlaceOrderRequest = {
       "coin": "BTC",
       "is_buy": True,
       "sz": desired_size,
       "px": limit_price,
       "is_market": False,
       "order_type": limit_order_type(TimeInForce.GTC),
   }

Submit with ``place_limit_order(request)`` or place a same-asset-class tuple with
``place_orders(requests)``. A perpetual tuple may span the base and HIP-3 DEXes;
it cannot include spot or outcome markets. ``place_order(...)`` is an expanded
convenience form. ``place_market_order()`` and ``is_market=True`` derive an
aggressive limit price from the current mid and ``slippage``; the Exchange still
decides whether the order fills. Slippage must be finite and in ``[0, 1)``.

``TimeInForce.ALO`` rejects an order that would immediately cross,
``TimeInForce.IOC`` cancels any unfilled remainder, and ``TimeInForce.GTC`` may
rest. A ``Cloid`` is a validated 16-byte client order ID useful for idempotent
application tracking. The SDK does not guarantee server-side deduplication for
arbitrary retries.

Triggers and TP/SL
------------------

Build trigger options with ``trigger_order_type()`` and submit a
``PlaceOrderRequest`` through ``place_trigger_order()`` or ``place_orders()``.
The outer ``is_market`` must be false for a trigger; ``trigger.isMarket`` selects
the child execution style.

For grouped TP/SL, pass ``OrderGrouping.NORMAL_TPSL`` with a non-trigger parent
first and one or more trigger children after it. Position TP/SL uses
``OrderGrouping.POSITION_TPSL``. Set ``ro=True`` for reductions where applicable.
Do not use the outer market flag with a trigger order.

TWAP
----

``place_twap()`` accepts coin, direction, size, duration in minutes, optional
randomization, and optional reduce-only behavior. It also accepts optional
``trigger_px`` and ``stop_px`` advanced prices. Trigger activation direction is
inferred by comparing ``trigger_px`` with the current mark price. TWAP prices
are normalized using the resolved venue precision. Cancel a running TWAP with
``cancel_twap(coin, twap_id)``.

Cancellation and modification
-----------------------------

Use ``CancelOrder(coin, oid)`` with ``cancel_order()`` or ``cancel_orders()``.
Use ``CancelByCloid(coin, cloid)`` with ``cancel_by_cloid()`` or
``cancel_orders_by_cloid()``. Empty batches are rejected locally.

``ModifyOrderRequest`` identifies the order by integer order ID or ``Cloid`` and
contains the complete replacement order. ``modify_order()`` returns a default
acknowledgement; ``modify_orders()`` returns per-order statuses.

``client.exchange.schedule_cancel(cancel_at)`` schedules dead-man cancellation
using an absolute millisecond timestamp; passing no timestamp removes the
schedule according to Exchange semantics.

Closing and risk settings
-------------------------

``close_position()`` and ``close_positions()`` read each full current position
and submit reduce-only market orders. Despite its name,
``close_all_positions(dexs=None)`` does not discover every HIP-3 DEX. It uses
the ``dexs`` configured on ``AsyncHyperliquid``; the constructor default is
``("",)``, which scans only the base perpetual DEX. Include every intended
HIP-3 DEX explicitly in the constructor or in the ``close_all_positions(dexs=)``
call. Re-query final positions through a trusted Info endpoint. These methods
are not partial-close helpers; use an explicit reduce-only order for a partial
reduction.

``update_leverage()`` and ``update_isolated_margin()`` resolve the coin's asset
ID before signing. Treat both as risk-changing operations and verify resulting
account state independently.

Responses
---------

Transport success does not imply action success. Inspect the top-level
``response["status"]``. Only when it is ``"ok"`` should an application inspect
each item in ``response["response"]["data"]["statuses"]`` for resting, filled,
waiting, or error status. When the top-level status is ``"err"``,
``response["response"]`` is the rejection string instead of the success
envelope. See :doc:`../reference/response-types` and
:doc:`lifecycle-reconciliation`.
