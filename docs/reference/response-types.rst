Detailed response types
=======================

Info responses
--------------

Info response objects are ``TypedDict`` classes and type aliases preserving
Hyperliquid's wire field names. Numeric wire fields remain strings.

.. automodule:: async_hyperliquid.types.info
   :members:
   :undoc-members:

Exchange response envelopes
---------------------------

Every Exchange response has a top-level ``status``. Successful order, cancel,
and TWAP responses contain operation-specific data; a default success contains
only the default acknowledgement. A protocol rejection is an ``ExchangeError``
with ``status == "err"`` and a string ``response``.

The public aliases :data:`async_hyperliquid.types.PlaceOrderResponse`,
:data:`async_hyperliquid.types.CancelOrderResponse`,
:data:`async_hyperliquid.types.PlaceTwapResponse`,
:data:`async_hyperliquid.types.CancelTwapResponse`,
:data:`async_hyperliquid.types.DefaultActionResponse`, and
:data:`async_hyperliquid.types.ActionResponse` compose the detailed shapes
below.

.. automodule:: async_hyperliquid.types.exchange
   :members: RestingOrderStatus, RestingStatus, FilledOrderStatus, FilledStatus, ErrorStatus, OrderStatusTag, OrderStatus, CancelStatus, OrderResponseData, OrderResponse, PlaceOrderSuccess, CancelResponseData, CancelResponse, CancelSuccess, TwapRunningData, TwapRunningStatus, TwapOrderStatus, TwapOrderResponseData, TwapOrderResponse, TwapOrderSuccess, TwapCancelResponseData, TwapCancelResponse, TwapCancelSuccess, DefaultResponse, DefaultSuccess, ExchangeError
   :undoc-members:
