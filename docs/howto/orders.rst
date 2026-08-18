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

The following snippets are independent ``async main`` fragments. They assume an
authenticated testnet ``client`` prepared as shown in
:doc:`../introduction/quickstart` and protect a long BTC perpetual position.
Replace ``size`` with the amount that may actually be reduced. Do not adapt a
long exit to a short position by changing only ``is_buy``; a buy exit also needs
an execution price above its trigger.

Common setup
~~~~~~~~~~~~

Read the mark and venue precision instead of hard-coding prices and sizes. TP/SL
orders trigger on the mark price. A market-style trigger still needs ``px`` in
the signed request; the examples use an aggressive execution price below the
sell trigger.

.. code-block:: python

   from async_hyperliquid.types import (
       OrderGrouping,
       PlaceOrderRequest,
       TimeInForce,
       TriggerKind,
       limit_order_type,
       trigger_order_type,
   )

   coin = "BTC"
   mark_px = await client.info.mark_price(coin)
   size_decimals = await client.info.size_decimals(coin)
   size = round(20 / mark_px, size_decimals)

   take_trigger_px = float(f"{mark_px * 1.10:.5g}")
   stop_trigger_px = float(f"{mark_px * 0.90:.5g}")
   take_execution_px = float(f"{take_trigger_px * 0.90:.5g}")
   stop_execution_px = float(f"{stop_trigger_px * 0.90:.5g}")

   def require_order_statuses(response):
       if response["status"] == "err":
           raise RuntimeError(response["response"])
       statuses = response["response"]["data"]["statuses"]
       errors = [
           status["error"]
           for status in statuses
           if isinstance(status, dict) and "error" in status
       ]
       if errors:
           raise RuntimeError("; ".join(errors))
       return statuses


Short-position price setup
~~~~~~~~~~~~~~~~~~~~~~~~~~

For a short position, use ``is_buy=True`` and keep ``ro=True`` in the exit
requests below. The take-profit trigger is below the mark, the stop-loss trigger
is above it, and both aggressive buy execution prices are above their triggers:

.. code-block:: python

   short_take_trigger_px = float(f"{mark_px * 0.90:.5g}")
   short_stop_trigger_px = float(f"{mark_px * 1.10:.5g}")
   short_take_execution_px = float(f"{short_take_trigger_px * 1.10:.5g}")
   short_stop_execution_px = float(f"{short_stop_trigger_px * 1.10:.5g}")

Use the corresponding ``short_*`` values in one request shape below; do not
submit the long and short alternatives together. In the attached-parent shape,
a short-entry parent is a sell order (``is_buy=False``), while its TP/SL exit
children are buy orders (``is_buy=True``).

Standalone take profit
~~~~~~~~~~~~~~~~~~~~~~

The default ``OrderGrouping.NA`` places an ungrouped TP trigger:

.. code-block:: python

   take_profit: PlaceOrderRequest = {
       "coin": coin,
       "is_buy": False,
       "sz": size,
       "px": take_execution_px,
       "is_market": False,
       "ro": True,
       "order_type": trigger_order_type(
           is_market=True,
           trigger_px=str(take_trigger_px),
           tpsl=TriggerKind.TAKE_PROFIT,
       ),
   }
   response = await client.place_trigger_order(take_profit)
   statuses = require_order_statuses(response)

Standalone stop loss
~~~~~~~~~~~~~~~~~~~~

An ungrouped SL uses the same request shape with ``TriggerKind.STOP_LOSS``:

.. code-block:: python

   stop_loss: PlaceOrderRequest = {
       "coin": coin,
       "is_buy": False,
       "sz": size,
       "px": stop_execution_px,
       "is_market": False,
       "ro": True,
       "order_type": trigger_order_type(
           is_market=True,
           trigger_px=str(stop_trigger_px),
           tpsl=TriggerKind.STOP_LOSS,
       ),
   }
   response = await client.place_trigger_order(stop_loss)
   statuses = require_order_statuses(response)

TP and SL attached to a parent order
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Put the non-trigger parent first, followed by its TP and SL children. The
Exchange activates the children according to the parent's fill and cancellation
state; inspect all three returned statuses.

.. code-block:: python

   entry_px = float(f"{mark_px * 0.95:.5g}")
   parent: PlaceOrderRequest = {
       "coin": coin,
       "is_buy": True,
       "sz": size,
       "px": entry_px,
       "is_market": False,
       "order_type": limit_order_type(TimeInForce.GTC),
   }
   parent_take_profit: PlaceOrderRequest = {
       "coin": coin,
       "is_buy": False,
       "sz": size,
       "px": take_execution_px,
       "is_market": False,
       "ro": True,
       "order_type": trigger_order_type(
           is_market=True,
           trigger_px=str(take_trigger_px),
           tpsl=TriggerKind.TAKE_PROFIT,
       ),
   }
   parent_stop_loss: PlaceOrderRequest = {
       "coin": coin,
       "is_buy": False,
       "sz": size,
       "px": stop_execution_px,
       "is_market": False,
       "ro": True,
       "order_type": trigger_order_type(
           is_market=True,
           trigger_px=str(stop_trigger_px),
           tpsl=TriggerKind.STOP_LOSS,
       ),
   }

   response = await client.place_orders(
       (parent, parent_take_profit, parent_stop_loss),
       grouping=OrderGrouping.NORMAL_TPSL,
   )
   statuses = require_order_statuses(response)

Position take profit
~~~~~~~~~~~~~~~~~~~~

Use ``POSITION_TPSL`` when the TP belongs to an existing position:

.. code-block:: python

   position_take_profit: PlaceOrderRequest = {
       "coin": coin,
       "is_buy": False,
       "sz": size,
       "px": take_execution_px,
       "is_market": False,
       "ro": True,
       "order_type": trigger_order_type(
           is_market=True,
           trigger_px=str(take_trigger_px),
           tpsl=TriggerKind.TAKE_PROFIT,
       ),
   }
   response = await client.place_trigger_order(
       position_take_profit,
       grouping=OrderGrouping.POSITION_TPSL,
   )
   statuses = require_order_statuses(response)

Position stop loss
~~~~~~~~~~~~~~~~~~

The corresponding position SL only changes the trigger kind and prices:

.. code-block:: python

   position_stop_loss: PlaceOrderRequest = {
       "coin": coin,
       "is_buy": False,
       "sz": size,
       "px": stop_execution_px,
       "is_market": False,
       "ro": True,
       "order_type": trigger_order_type(
           is_market=True,
           trigger_px=str(stop_trigger_px),
           tpsl=TriggerKind.STOP_LOSS,
       ),
   }
   response = await client.place_trigger_order(
       position_stop_loss,
       grouping=OrderGrouping.POSITION_TPSL,
   )
   statuses = require_order_statuses(response)

Set ``trigger_order_type(is_market=False, ...)`` and choose ``px`` as the child
limit price for a limit-style TP/SL. A more aggressive child price improves its
chance of filling after activation but permits more slippage. Always reconcile
the resulting order and position state.

TWAP
----

``place_twap()`` accepts coin, direction, size, duration in minutes, optional
randomization, and optional reduce-only behavior. It also accepts optional
``trigger_px`` and ``stop_px`` advanced prices. Trigger activation direction is
inferred by comparing ``trigger_px`` with the current mark price. TWAP prices
are normalized using the resolved venue precision. Cancel a running TWAP with
``cancel_twap(coin, twap_id)``.

Each block below is a separate ``async main`` fragment and places one real TWAP.
Run only the block you intend. ``trigger_px`` controls when the TWAP starts;
``stop_px`` is the price boundary that stops the TWAP, not a TP/SL child order.

Common setup
~~~~~~~~~~~~

.. code-block:: python

   coin = "BTC"
   mark_px = await client.info.mark_price(coin)
   size_decimals = await client.info.size_decimals(coin)
   size = round(120 / mark_px, size_decimals)
   start_below = float(f"{mark_px * 0.95:.5g}")
   stop_above = float(f"{mark_px * 1.05:.5g}")

   def require_running_twap(response):
       if response["status"] == "err":
           raise RuntimeError(response["response"])
       status = response["response"]["data"]["status"]
       if "error" in status:
           raise RuntimeError(status["error"])
       return status["running"]["twapId"]

   def require_twap_cancelled(response):
       if response["status"] == "err":
           raise RuntimeError(response["response"])
       status = response["response"]["data"]["status"]
       if status != "success":
           raise RuntimeError(status["error"])


Basic TWAP
~~~~~~~~~~

Start immediately:

.. code-block:: python

   response = await client.place_twap(
       coin,
       True,
       size,
       5,
       randomize=True,
   )
   twap_id = require_running_twap(response)

Triggered start
~~~~~~~~~~~~~~~

Start when the mark reaches ``start_below``:

.. code-block:: python

   response = await client.place_twap(
       coin,
       True,
       size,
       5,
       trigger_px=start_below,
   )
   twap_id = require_running_twap(response)

Stop boundary
~~~~~~~~~~~~~

Start immediately and stop at ``stop_above``:

.. code-block:: python

   response = await client.place_twap(
       coin,
       True,
       size,
       5,
       stop_px=stop_above,
   )
   twap_id = require_running_twap(response)

Triggered start with stop boundary
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Wait for ``start_below``, then stop at ``stop_above``:

.. code-block:: python

   response = await client.place_twap(
       coin,
       True,
       size,
       5,
       randomize=True,
       trigger_px=start_below,
       stop_px=stop_above,
   )
   twap_id = require_running_twap(response)

Cancellation
~~~~~~~~~~~~

Each placement block assigns the validated running ``twap_id``. Retain it and
cancel that one TWAP when it should no longer run:

.. code-block:: python

   cancel_response = await client.cancel_twap(coin, twap_id)
   require_twap_cancelled(cancel_response)

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
schedule according to Exchange semantics. The scheduled time must be at least
five seconds in the future. At most ten scheduled cancels may trigger per day;
the count resets at 00:00 UTC.

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
