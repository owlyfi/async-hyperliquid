AsyncHyperliquid
================

.. warning::

   This reference includes methods that place, modify, cancel, and close orders;
   change leverage or margin; and move assets. A signature is not a safety
   procedure. Before calling them, read :doc:`../howto/orders`,
   :doc:`../howto/routing`, :doc:`../howto/transfers-administration`, and
   :doc:`../howto/lifecycle-reconciliation`. Start on testnet and reconcile every
   ambiguous signed outcome before replacement.

.. autoclass:: async_hyperliquid.AsyncHyperliquid
   :members:
   :undoc-members:

Use the root client for workflows that resolve coins, metadata, prices, token
precision, or positions. Use ``.info`` for reads and ``.exchange`` for the
Info-independent actions listed in :doc:`exchange-client`.
