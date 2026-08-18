AsyncHyperliquid
================

.. warning::

   This reference includes methods that place, modify, cancel, and close orders;
   change leverage or margin; and move assets. A signature is not a safety
   procedure. Before calling them, read :doc:`../howto/orders`,
   :doc:`../howto/routing`, :doc:`../howto/transfers-administration`, and
   :doc:`../howto/lifecycle-reconciliation`. Start on testnet and reconcile every
   ambiguous signed outcome before replacement.

Shared contract
---------------

Use the root client for workflows that resolve coins, metadata, prices, token
precision, or positions. Use ``.info`` for reads and ``.exchange`` for the
Info-independent actions listed in :doc:`exchange-client`.

* Use the client as an async context manager, or pair ``open()`` with
  ``close()``. The root client owns the shared HTTP transport.
* Public amounts, prices, and sizes are human-readable ``float`` values. The
  client resolves venue metadata before encoding; consult
  :doc:`../howto/markets` for accepted coin names and precision behavior.
* Signed methods return a typed success-or-rejection union. ``status == "err"``
  is returned data, while local validation, transport, and malformed-response
  failures raise exceptions. See :doc:`response-types` and :doc:`errors`.
* A timeout does not prove that a signed action failed. The client does not
  retry signed actions automatically; reconcile through trusted Info reads
  before replacement.

The method signatures below are the authoritative parameter and return-type
reference. The order and transfer guides define the required safety procedure
and response handling without repeating it under every method.

.. autoclass:: async_hyperliquid.AsyncHyperliquid
   :members:
   :undoc-members:
