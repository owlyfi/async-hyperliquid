ExchangeClient
==============

.. danger::

   This reference includes fund-moving, paid, authority-changing, outcome, and
   validator actions. Some actions are irreversible and user-signed fund actions
   have no ``expires_after`` protection. Do not invoke a method from its
   signature alone. Read :doc:`../howto/orders`, :doc:`../howto/routing`,
   :doc:`../howto/transfers-administration`, and
   :doc:`../howto/lifecycle-reconciliation` first.

Shared contract
---------------

Applications normally obtain this object from ``AsyncHyperliquid.exchange`` so
it shares lifecycle, transport, routing, and nonce ownership with the root
client.

* Do not construct this class directly. ``AsyncHyperliquid`` supplies the
  account, signer, network, routing scope, transport, and monotonic nonce owner.
* Amounts are human-readable units. USD sends, withdrawals, and class transfers
  truncate beyond 2 decimals; vault USD uses 6 decimals; HYPE uses 8; and token
  transfers use token metadata. See :doc:`../howto/transfers-administration`.
* ``expires_after`` is an absolute millisecond deadline and is available only
  where shown in the signature. It rejects a stale submission; it does not undo
  an acknowledged action or make an ambiguous timeout safe to retry.
* Default acknowledgements still return ``status == "err"`` for Exchange
  rejection. Order, cancel, and TWAP methods also contain operation-specific
  status data. Always discriminate the union described in
  :doc:`response-types`.
* These methods do not automatically retry. Reuse one client per execution
  address and follow :doc:`../howto/lifecycle-reconciliation` after uncertain
  outcomes.

The signatures below are the authoritative parameter and return-type reference;
the linked how-to guides supply the operation-specific safety procedure.

.. autoclass:: async_hyperliquid.exchange.ExchangeClient
   :members:
   :undoc-members:
