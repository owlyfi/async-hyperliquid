Commands, enums, and exported types
===================================

Enums and identifiers
---------------------

.. autoclass:: async_hyperliquid.types.Network
   :members:
   :undoc-members:

.. autoclass:: async_hyperliquid.types.TimeInForce
   :members:
   :undoc-members:

.. autoclass:: async_hyperliquid.types.TriggerKind
   :members:
   :undoc-members:

.. autoclass:: async_hyperliquid.types.OrderGrouping
   :members:
   :undoc-members:

.. autoclass:: async_hyperliquid.types.CandleInterval
   :members:
   :undoc-members:

.. autoclass:: async_hyperliquid.types.UserAbstraction
   :members:
   :undoc-members:

.. autoclass:: async_hyperliquid.types.AgentAbstraction
   :members:
   :undoc-members:

.. autoclass:: async_hyperliquid.types.Cloid
   :members:
   :undoc-members:

Order commands and builders
---------------------------

.. autoclass:: async_hyperliquid.types.CancelOrder
   :members:
   :undoc-members:

.. autoclass:: async_hyperliquid.types.CancelByCloid
   :members:
   :undoc-members:

.. autoclass:: async_hyperliquid.types.Builder
   :members:
   :undoc-members:

.. autoclass:: async_hyperliquid.types.BaseOrderRequest
   :members:
   :undoc-members:

.. autoclass:: async_hyperliquid.types.PlaceOrderRequest
   :members:
   :undoc-members:

.. autoclass:: async_hyperliquid.types.ModifyOrderRequest
   :members:
   :undoc-members:

.. autofunction:: async_hyperliquid.types.limit_order_type

.. autofunction:: async_hyperliquid.types.trigger_order_type

Option and JSON types
---------------------

.. autoclass:: async_hyperliquid.types.LimitOrderOption
   :members:
   :undoc-members:

.. autoclass:: async_hyperliquid.types.LimitOrderType
   :members:
   :undoc-members:

.. autoclass:: async_hyperliquid.types.TriggerOrderOption
   :members:
   :undoc-members:

.. autoclass:: async_hyperliquid.types.TriggerOrderType
   :members:
   :undoc-members:

.. autodata:: async_hyperliquid.types.OrderType

``JsonScalar`` is ``str | int | float | bool | None``. ``JsonValue`` recursively
adds JSON arrays and objects, and ``JsonObject`` is ``dict[str, JsonValue]``.
These aliases describe untyped protocol fragments and extension payloads.

Response aliases
----------------

.. autodata:: async_hyperliquid.types.PlaceOrderResponse

.. autodata:: async_hyperliquid.types.CancelOrderResponse

.. autodata:: async_hyperliquid.types.PlaceTwapResponse

.. autodata:: async_hyperliquid.types.CancelTwapResponse

.. autodata:: async_hyperliquid.types.DefaultActionResponse

.. autodata:: async_hyperliquid.types.ActionResponse
