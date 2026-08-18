InfoClient
==========

Shared contract
---------------

Info methods return the typed wire shape and do not require credentials. Account
addresses are query parameters; they do not become client state.

* Use an async context manager, or pair ``open()`` with ``close()``. Passing an
  existing ``aiohttp`` session leaves that session owned by the caller.
* Timestamps are integer milliseconds. Numeric fields in protocol-shaped
  responses remain strings unless a named convenience method, such as
  ``mark_price()`` or ``mid_price()``, declares a numeric return type.
* Metadata helpers cache one coherent metadata snapshot. Call
  ``refresh_metadata()`` when the application explicitly needs fresh listings.
  Separate Info requests are not an atomic account snapshot.
* Local argument errors raise ``ValueError``; transport failures and malformed
  upstream shapes raise the package exceptions in :doc:`errors`.

Use :doc:`../howto/info-queries` to choose an endpoint by task and
:doc:`../howto/markets` for canonical coin names. The signatures below remain
the authoritative parameter and return-type reference.

.. autoclass:: async_hyperliquid.InfoClient
   :members:
   :undoc-members:
