Introduction
============

The package has three main public entry points:

``InfoClient``
   Credential-free reads, market metadata, prices, orders, fills, portfolio,
   staking, vault, and deployment information.

``AsyncHyperliquid``
   The lifecycle owner for authenticated use. It combines ``.info`` and
   ``.exchange`` and implements workflows that must resolve market metadata,
   prices, or positions before signing.

``ExchangeClient``
   Available as ``client.exchange``. It exposes Info-independent signed actions
   such as transfers and account administration. Applications normally create
   ``AsyncHyperliquid`` rather than constructing it directly.

All network I/O is asynchronous. Constructors do not allocate an HTTP session;
``open()`` or an async context manager does. The client never automatically
retries a signed action.

Choosing a client
-----------------

Use ``InfoClient`` whenever no signed action is needed. It requires neither an
account address nor a private key. Account-specific Info methods accept the
address to query.

Use ``AsyncHyperliquid`` only when the process must sign. Keep the signing key
in a secret store, prefer an API wallet with narrowly scoped funds, and begin on
testnet. The ``account_address`` identifies the main account while
``signing_key`` may belong to its approved API wallet.

The package root intentionally exports only ``AsyncHyperliquid``,
``InfoClient``, and ``HyperliquidError``. Commands and enums are in
``async_hyperliquid.types``; detailed wire response types are in
``async_hyperliquid.types.info`` and ``async_hyperliquid.types.exchange``.
