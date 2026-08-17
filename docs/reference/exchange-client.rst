ExchangeClient
==============

.. danger::

   This reference includes fund-moving, paid, authority-changing, outcome, and
   validator actions. Some actions are irreversible and user-signed fund actions
   have no ``expires_after`` protection. Do not invoke a method from its
   signature alone. Read :doc:`../howto/orders`, :doc:`../howto/routing`,
   :doc:`../howto/transfers-administration`, and
   :doc:`../howto/lifecycle-reconciliation` first.

.. autoclass:: async_hyperliquid.exchange.ExchangeClient
   :members:
   :undoc-members:

Applications normally obtain this object from ``AsyncHyperliquid.exchange`` so
it shares lifecycle, transport, routing, and nonce ownership with the root
client.
