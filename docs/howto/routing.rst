Route accounts and endpoints
============================

Account, signer, and execution target
-------------------------------------

``account_address`` is the main account. ``signing_key`` may be the main key or
an approved API-wallet key. The signing key's public address is not the
portfolio address to use for ordinary Info queries.

When ``vault_address`` is omitted, execution targets the main account. When it
is supplied, ``client.exchange.execution_address`` is that vault or subaccount,
and execution-scoped actions and position queries target it. Root-scoped
administration actions still apply to the main account. Protocol-specific USD
class and asset transfers include the configured subaccount field.

Use ``InfoClient.user_role()`` to verify relationships before signing:

* an API wallet reports the agent role and its owning user;
* a subaccount reports the subaccount role and its master;
* portfolio queries use the main, subaccount, or vault address, not the API
  wallet address.

Create a separate immutable client for each execution target. Do not mutate
routing state between actions.

Network and URLs
----------------

``Network.MAINNET`` and ``Network.TESTNET`` choose both official defaults and
the signing domain. Custom ``info_url`` and ``exchange_url`` values are exact,
independent endpoints; they do not change the signing domain.

.. warning::

   A custom Exchange endpoint is a trusted execution boundary. It sees
   replayable signed envelopes and can delay, censor, or fabricate a plausible
   acknowledgement. The private key stays local, but this does not make the
   provider harmless.

.. warning::

   A custom Info endpoint attached to ``AsyncHyperliquid`` is trusted
   order-construction input. Its metadata and prices determine asset IDs,
   precision, market-order limits, and close sizes used in signed actions.

Reconcile signed outcomes through an independently trusted Info endpoint.
``expires_after`` is available only on methods whose protocol supports it and
does not add expiry to user-signed fund actions.

Sessions across origins
-----------------------

``client.info`` and ``client.exchange`` share the supplied ``aiohttp`` session.
Do not attach session-wide authorization headers or cookies when Info and
Exchange URLs use different origins. Use host-scoped middleware or separately
owned clients and sessions. Endpoint fallback, provider authentication, health
checks, and routing policy remain application responsibilities.
