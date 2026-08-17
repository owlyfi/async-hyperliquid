Quickstart
==========

Read market data safely
-----------------------

The safest first program is credential-free and performs no signed action:

.. code-block:: python

   import asyncio

   from async_hyperliquid import InfoClient
   from async_hyperliquid.types import Network


   async def main() -> None:
       async with InfoClient(network=Network.MAINNET) as info:
           print(await info.mid_price("BTC"))
           print(await info.coin_name("HYPE/USDC"))


   asyncio.run(main())

Inspect an account without signing
----------------------------------

An address is public query input, not a credential:

.. code-block:: python

   import asyncio
   import os

   from async_hyperliquid import InfoClient
   from async_hyperliquid.types import Network


   async def main() -> None:
       account_address = os.environ["HL_ACCOUNT_ADDRESS"]
       async with InfoClient(network=Network.MAINNET) as info:
           orders = await info.open_orders(account_address, frontend=True)
           positions = await info.positions(account_address)
           print(orders, positions)


   asyncio.run(main())

Prepare an authenticated client
--------------------------------

.. warning::

   A signing key authorizes real actions. Start with ``Network.TESTNET``, keep
   secrets out of source code and logs, and verify the account/API-wallet
   relationship before submitting anything.

Creating the client does not submit an action. This pattern lets an application
verify routing and read state before enabling a trading command:

.. code-block:: python

   import asyncio
   import os

   from eth_account import Account
   from eth_utils import is_same_address

   from async_hyperliquid import AsyncHyperliquid
   from async_hyperliquid.types import Network


   async def main() -> None:
       account_address = os.environ["HL_ACCOUNT_ADDRESS"]
       signing_key = os.environ["HL_SIGNING_KEY"]
       subaccount_address = os.environ.get("HL_SUBACCOUNT_ADDRESS")
       signer_address = Account.from_key(signing_key).address

       async with AsyncHyperliquid(
           account_address=account_address,
           signing_key=signing_key,
           vault_address=subaccount_address,
           network=Network.TESTNET,
       ) as client:
           if not is_same_address(signer_address, account_address):
               signer_role = await client.info.user_role(signer_address)
               if signer_role["role"] != "agent" or not is_same_address(
                   signer_role["data"]["user"], account_address
               ):
                   raise RuntimeError(
                       "signing key is not an API wallet for the main account"
                   )

           if subaccount_address is not None:
               execution_role = await client.info.user_role(subaccount_address)
               if execution_role["role"] != "subAccount" or not is_same_address(
                   execution_role["data"]["master"], account_address
               ):
                   raise RuntimeError(
                       "execution target is not a subaccount of the main account"
                   )

           positions = await client.info.positions(
               client.exchange.execution_address
           )
           print(positions)


   asyncio.run(main())

The signer address is derived locally from the key and is never confused with
the execution address. A main-account key must derive to ``account_address``;
otherwise the signer must have the agent role owned by that account. When the
optional subaccount is configured, its role must identify the same main account
as master. A vault requires its own protocol-specific relationship checks; do
not pass a vault through the subaccount variable.

Read :doc:`../howto/routing` before supplying a vault address or custom URL,
and :doc:`../howto/lifecycle-reconciliation` before submitting signed actions.
