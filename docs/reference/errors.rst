Errors
======

.. automodule:: async_hyperliquid.errors
   :members:
   :undoc-members:

``HttpError`` can occur on unsigned Info calls. For signed calls, ambiguous
timeout, HTTP, and protocol failures are converted to
``IndeterminateActionError`` so applications do not mistake them for confirmed
rejections. See :doc:`../howto/lifecycle-reconciliation`.
