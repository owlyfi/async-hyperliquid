Transfers and administration
============================

.. danger::

   The methods on this page can move funds, spend fees, change account authority,
   alter protocol state, or perform irreversible conversions. The transfer
   examples are executable signed-action fragments: copying and running one can
   move real assets. Confirm the network, execution address, destination, units,
   permissions, and recovery procedure before signing, and start on testnet.

Fund movement
-------------

Coin-resolving methods live on ``AsyncHyperliquid``:

* ``spot_transfer`` sends a spot token after resolving its token metadata;
* ``send_asset`` moves a token between DEX contexts or destinations;
* ``agent_send_asset`` submits the agent-signed variant;
* ``send_to_evm_with_data`` sends a token to an external-chain recipient with
  caller-supplied encoding, chain ID, gas limit, and data.

Info-independent methods live on ``client.exchange``:

* ``usd_transfer`` sends USD;
* ``withdraw`` initiates a withdrawal;
* ``usd_class_transfer`` moves USD between spot and perpetual classes;
* ``vault_transfer`` deposits to or withdraws from a vault;
* ``hip3_liquidator_transfer`` moves quote notional for a HIP-3 liquidator;
* ``staking_deposit``, ``staking_withdraw``, and ``token_delegate`` change
  staking balances or delegation.

User-signed fund actions do not accept ``expires_after``. A timeout still leaves
their result indeterminate; reconcile balances and ledgers before replacement.

Transfer examples
~~~~~~~~~~~~~~~~~

The examples below are independent ``async main`` fragments, not a sequence to
run. They assume an authenticated testnet ``client`` prepared as shown in
:doc:`../introduction/quickstart`. Supply every value explicitly through your
environment, inspect it before signing, and run only the one operation you
intend. The SDK does not verify that a destination belongs to you.

Response check
^^^^^^^^^^^^^^

Run the chosen operation after this small response helper. An Exchange rejection
is returned as data instead of raised as a Python exception.

.. code-block:: python

   import os

   def require_ok(response):
       if response["status"] == "err":
           raise RuntimeError(response["response"])

Amounts are human-readable units. The SDK truncates excess fractional digits
toward zero when encoding these actions: USD sends, withdrawals, and class
transfers use 2 decimals; vault USD uses 6; HYPE uses 8; and token transfers use
the token's ``weiDecimals`` metadata. Validate or quantize the input yourself if
silent truncation is not acceptable. The HIP-3 liquidator call instead requires
no more than 6 decimal places and an exact multiple of 1,000 quote tokens.

Direct account transfers
^^^^^^^^^^^^^^^^^^^^^^^^

Send a spot token after resolving ``coin`` to its token ID and decimals:

.. code-block:: python

   coin = os.environ["HL_TRANSFER_COIN"]
   token_amount = float(os.environ["HL_TRANSFER_TOKEN_AMOUNT"])
   destination = os.environ["HL_TRANSFER_DESTINATION"]
   response = await client.spot_transfer(
       coin,
       token_amount,
       destination,
   )
   require_ok(response)

Send USD directly to another address:

.. code-block:: python

   usd_amount = float(os.environ["HL_TRANSFER_USD_AMOUNT"])
   destination = os.environ["HL_TRANSFER_DESTINATION"]
   response = await client.exchange.usd_transfer(
       usd_amount,
       destination,
   )
   require_ok(response)

Initiate a withdrawal to an explicit destination. Omitting ``destination`` uses
the configured account address, but an explicit value is easier to audit. The
official Exchange API currently documents a $1 fee and approximately five
minutes to finality; verify the current terms in the `Exchange endpoint`_ before
signing:

.. code-block:: python

   usd_amount = float(os.environ["HL_TRANSFER_USD_AMOUNT"])
   destination = os.environ["HL_TRANSFER_DESTINATION"]
   response = await client.exchange.withdraw(
       usd_amount,
       destination=destination,
   )
   require_ok(response)

DEX and external destinations
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Move a token between DEX contexts with a user-signed ``send_asset`` action. Use
``""`` for the default USDC perpetual DEX and ``"spot"`` for spot. Only the
collateral token may move to or from a perpetual DEX; see `Send Asset`_:

.. code-block:: python

   coin = os.environ["HL_TRANSFER_COIN"]
   token_amount = float(os.environ["HL_TRANSFER_TOKEN_AMOUNT"])
   destination = os.environ["HL_TRANSFER_DESTINATION"]
   response = await client.send_asset(
       coin,
       token_amount,
       destination,
       source_dex=os.environ["HL_SOURCE_DEX"],
       destination_dex=os.environ["HL_DESTINATION_DEX"],
   )
   require_ok(response)

The agent-signed variant accepts ``expires_after``. The deadline is an absolute
millisecond timestamp and does not make an acknowledged transfer reversible:

.. code-block:: python

   from time import time_ns

   coin = os.environ["HL_TRANSFER_COIN"]
   token_amount = float(os.environ["HL_TRANSFER_TOKEN_AMOUNT"])
   destination = os.environ["HL_TRANSFER_DESTINATION"]
   expires_after = time_ns() // 1_000_000 + 30_000
   response = await client.agent_send_asset(
       coin,
       token_amount,
       destination,
       source_dex=os.environ["HL_SOURCE_DEX"],
       destination_dex=os.environ["HL_DESTINATION_DEX"],
       expires_after=expires_after,
   )
   require_ok(response)

For an external EVM destination, provide the chain, gas, recipient encoding, and
call data. ``data="0x"`` means no call data; use non-empty data only after
validating the destination contract and payload outside the SDK:

.. code-block:: python

   coin = os.environ["HL_TRANSFER_COIN"]
   token_amount = float(os.environ["HL_TRANSFER_TOKEN_AMOUNT"])
   response = await client.send_to_evm_with_data(
       coin,
       token_amount,
       os.environ["HL_EVM_RECIPIENT"],
       source_dex=os.environ["HL_SOURCE_DEX"],
       address_encoding="hex",
       destination_chain_id=int(os.environ["HL_DESTINATION_CHAIN_ID"]),
       gas_limit=int(os.environ["HL_EVM_GAS_LIMIT"]),
       data=os.environ.get("HL_EVM_CALL_DATA", "0x"),
   )
   require_ok(response)

USD classes
^^^^^^^^^^^

Move USD from spot to perpetuals with ``to_perp=True``. Use ``False`` for the
reverse direction; do not run both calls merely to test connectivity:

.. code-block:: python

   usd_amount = float(os.environ["HL_TRANSFER_USD_AMOUNT"])
   response = await client.exchange.usd_class_transfer(
       usd_amount,
       to_perp=True,
   )
   require_ok(response)

Vault and HIP-3 transfers
^^^^^^^^^^^^^^^^^^^^^^^^^

Deposit USD into a vault with ``is_deposit=True``. Use ``False`` only when you
intend to withdraw from that vault:

.. code-block:: python

   response = await client.exchange.vault_transfer(
       os.environ["HL_VAULT_ADDRESS"],
       float(os.environ["HL_VAULT_USD_AMOUNT"]),
       is_deposit=True,
   )
   require_ok(response)

A HIP-3 liquidator transfer requires a positive amount that is an exact multiple
of 1,000 quote tokens. Use ``is_deposit=False`` for the reverse direction:

.. code-block:: python

   response = await client.exchange.hip3_liquidator_transfer(
       os.environ["HL_HIP3_DEX"],
       float(os.environ["HL_HIP3_QUOTE_AMOUNT"]),
       is_deposit=True,
   )
   require_ok(response)

Staking and delegation
^^^^^^^^^^^^^^^^^^^^^^

Move HYPE into the staking balance:

.. code-block:: python

   response = await client.exchange.staking_deposit(
       float(os.environ["HL_STAKING_HYPE_AMOUNT"]),
   )
   require_ok(response)

Move HYPE out of the staking balance. This starts a seven-day unstaking queue;
an address may have at most five pending withdrawals:

.. code-block:: python

   response = await client.exchange.staking_withdraw(
       float(os.environ["HL_STAKING_HYPE_AMOUNT"]),
   )
   require_ok(response)

Delegate HYPE to a validator. Set ``undelegate=True`` only for the reverse
operation. Delegation to a validator has a one-day lockup; see `Staking`_:

.. code-block:: python

   response = await client.exchange.token_delegate(
       os.environ["HL_VALIDATOR_ADDRESS"],
       float(os.environ["HL_DELEGATION_HYPE_AMOUNT"]),
       undelegate=False,
   )
   require_ok(response)

Account administration
----------------------

The Exchange client exposes ``set_referrer_code``, ``create_sub_account``,
``use_big_blocks``, ``approve_agent``, ``approve_builder_fee``,
``convert_to_multi_sig_user``, account-abstraction methods, and agent-abstraction
methods. Approval and multisig changes alter authority; conversion may not have
a simple inverse. Read the current role and abstraction state first, then verify
it again through trusted Info after acknowledgement.

``reserve_request_weight`` is a paid action. ``schedule_cancel`` affects open
orders. ``noop`` advances or reserves the client's nonce stream. None should be
used as a generic health check.

Outcome and validator actions
-----------------------------

``split_outcome``, ``merge_outcome``, ``merge_question``, and
``negate_outcome`` alter outcome-token state. ``vote_risk_free_rate`` and
``authorize_aqav2_role`` are privileged validator or administrative actions.
``claim_rewards`` changes claimable state. Validate protocol-specific
eligibility and units outside the SDK before calling them.

Response discipline
-------------------

These methods usually return ``DefaultActionResponse``. A returned JSON object
may still have ``status == "err"``; that is an Exchange rejection, not a Python
exception. Network ambiguity is handled separately as described in
:doc:`lifecycle-reconciliation`.

.. _Exchange endpoint: https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/exchange-endpoint
.. _Send Asset: https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/exchange-endpoint#send-asset
.. _Staking: https://hyperliquid.gitbook.io/hyperliquid-docs/hypercore/staking
