Lifecycle, errors, and reconciliation
=====================================

Session ownership
-----------------

Use an async context manager whenever practical:

.. code-block:: python

   async with InfoClient() as info:
       mids = await info.all_mids()

``open()`` lazily opens internally managed resources. ``close()`` is idempotent.
An internally created ``aiohttp.ClientSession`` is owned and closed by the
client. A supplied session is borrowed and remains the caller's responsibility.
A closed transport cannot be reopened; create a new client instead.

Failure classes
---------------

``HyperliquidError`` is the package base exception. ``HttpError`` represents a
request failure or non-success HTTP status and exposes ``status`` when one is
available. ``ProtocolError`` means a response did not match the expected JSON
shape.

``ValueError`` is used for rejected local inputs such as unknown coins, empty
batches, invalid slippage, negative IDs, malformed endpoints, or invalid
``Cloid`` values. Exchange-level rejections are returned as typed
``{"status": "err", "response": ...}`` values and must be checked explicitly.

Signed actions are not retried
------------------------------

The SDK never automatically retries a signed action. If a timeout, HTTP error,
or malformed response occurs after submission may have happened,
``IndeterminateActionError`` carries the signed ``action_type`` and ``nonce``.
It does not prove that the Exchange rejected the action.

Reconcile before replacement
----------------------------

After an indeterminate result:

1. Stop automatic replacement for that intent.
2. Record the action type, nonce, intended execution address, and client order
   ID without logging the private key or signature.
3. Query an independently trusted Info endpoint.
4. For orders, inspect ``order_status()``, ``open_orders()``, ``user_fills()``,
   or ``historical_orders()`` using the execution address.
5. For transfers or administrative actions, inspect the corresponding balance,
   ledger, role, vault, staking, or abstraction state.
6. Submit a replacement only after application policy determines the original
   did not take effect.

Nonce ownership
---------------

Nonce monotonicity is local to one ``ExchangeClient``. Keep one live Exchange
owner per API-wallet private key. If processes share a key, the application must
serialize submissions and coordinate nonces across processes; the SDK is not a
distributed nonce service.

Cancellation itself can also become indeterminate. Use a ``Cloid`` where
possible, verify final order state, and do not infer cancellation merely from a
local exception.
