Transfers and administration
============================

.. danger::

   The methods on this page can move funds, spend fees, change account authority,
   alter protocol state, or perform irreversible conversions. They are listed
   for discovery only. Do not invoke them from copied examples. Confirm the
   selected network, execution address, destination, units, permissions, and
   rollback procedure in your own application before signing.

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
