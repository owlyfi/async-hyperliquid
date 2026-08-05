# Dual-Network Info and Vault Parity Design

## Goal

Make the integration suite exercise every read-only Info contract against both
Hyperliquid networks, remove redundant execution switches, and prove that
subaccount order routing matches the official SDK whether the root client is
constructed with the master or subaccount address.

The change also finishes two naming cleanups: the market-price helper should
describe its responsibility rather than its IOC limit implementation, and Info
integration test names should not repeat their file and directory context.

## Boundaries

- Production behavior changes only by renaming the private
  `_market_limit_price` helper to `_market_price`; no public API changes.
- Info availability policy exists only in integration support. Production
  `InfoClient` keeps its current HTTP and error semantics.
- No compatibility aliases are retained for either private helper rename.
- Copycat and other repositories are out of scope.
- Tests never log or persist private keys, signatures, or full signed payloads.

## Integration execution controls

Remove these environment gates:

- `RUN_INFO_TESTS`
- `RUN_MAINNET_INFO_TESTS`
- `RUN_EXCHANGE_TESTS`
- `RUN_DESTRUCTIVE_EXCHANGE_TESTS`

Remove the `mainnet_info` and `destructive_exchange` markers and the destructive
autouse fixture. Keep `info` and `exchange` only as descriptive pytest
categories; they do not control execution.

`IS_MAINNET` belongs exclusively to Exchange integration. Exchange fixture
setup calls the existing testnet hard gate before credentials or signed
requests. `IS_MAINNET=true` is an error; `IS_MAINNET=false` permits the
Exchange integration suite to execute without another opt-in.

Info integration never reads `IS_MAINNET` and has no opt-in. Invoking
`tests/integration/test_info.py` always runs both public networks. Repository
documentation must stop describing a plain all-tests invocation as a
deterministic offline suite; the explicit deterministic path list remains the
offline command used by CI.

## Dual-network Info fixture

The session-scoped `info` fixture is parameterized with stable IDs `mainnet`
and `testnet`. Each parameter owns one integration-only Info client and one
metadata cache. The shared `markets` fixture derives a live perp, spot market,
token ID, and perp dex list independently for each network.

Every common public Info endpoint test consumes this parameterized fixture and
therefore executes once per network. Account-query endpoints use only the
public values `HL_ADDR`, `HL_AK`, and `HL_SUB`; they never read `HL_PK` or
`HL_SK`. Ownership validation for the API wallet and subaccount remains in the
Exchange fixture, where it protects signed execution. The Info `user_role`
case validates response shape on both networks without assuming the same role
relationships exist on both ledgers.

The old standalone `mainnet_info` fixture and separately gated mainnet cases
are removed. Mainnet-specific alias expectations remain explicit tests driven
by the parameterized network rather than a second client hierarchy.

## Network-specific market contracts

The suite pins protocol identifiers that are intentionally different across
networks:

| Network | Public pair | Protocol coin | Asset ID |
|---|---|---:|---:|
| Mainnet | `HYPE/USDC` | `@107` | `10107` |
| Testnet | `HYPE/USDC` | `@1035` | `11035` |
| Mainnet | `PURR/USDC` | `PURR/USDC` | `10000` |

For each applicable row, the test validates `coin_name`, `asset_id`,
`coin_symbol`, metadata lookup, and mid-price lookup against `allMids`.
`PURR/USDC` must not be canonicalized to `@0`. Testnet PURR is validated from
its own live metadata and is not forced to reuse the mainnet asset ID.

Generic `coin_name`, `coin_symbol`, `asset_id`, `size_decimals`, token ID,
spot-token metadata, mark price, and mid price assertions run for dynamically
selected perp and spot markets on both networks. Outcome-market assertions run
where the network advertises an outcome market and skip only when that feature
is absent.

## Read-only availability policy

An integration-only `InfoClient` subclass owns transient availability handling
by overriding `_post` and calling the production implementation directly. It
does not wrap individual public methods and does not modify pytest reports.

For each request:

1. On the first HTTP `429`, await exactly 60 seconds and retry that request
   once.
2. If the retry is also `429`, skip the current test case. Never retry or wait
   again for that request.
3. On a TESTNET `5xx`, emit a warning containing only the status and request
   type, then skip the current case. This applies to either the initial attempt
   or the retry.
4. On a MAINNET `5xx`, fail normally.
5. Other HTTP failures, timeouts, invalid JSON, and protocol-shape failures
   fail normally on both networks.

Unit tests patch the sleep coroutine, so the retry policy is proven without a
real 60-second test delay. Live integration tests use the real delay.

## Exchange vault parity

The official SDK stores `account_address`, but its order path builds and signs
the action from the wallet, nonce, expiry, and `vault_address`. Therefore these
two configurations should produce the same order payload when all signed
inputs are fixed:

1. `account_address=HL_ADDR`, `vault_address=HL_SUB`, signer `HL_SK`.
2. `account_address=HL_SUB`, `vault_address=HL_SUB`, signer `HL_SK`.

The offline oracle constructs both official-SDK and async-hyperliquid clients,
freezes the nonce, submits the same native order batch into recording
transports, and asserts:

- each complete `/exchange` payload equals the corresponding official SDK
  payload;
- each envelope contains `vaultAddress == HL_SUB`;
- the two async-hyperliquid payloads are identical;
- the two official SDK payloads are identical.

This test uses `.env.local` values but performs no network request.

Integration adds two separately named order cases and two fixtures:

- `hl`: master `account_address`, API-wallet signer, subaccount vault;
- `sub_hl`: subaccount `account_address`, the same signer, the same vault.

Each case places a resting testnet order, verifies it through `HL_SUB`, and
cancels it in `finally`. This proves both initializations route execution to
the subaccount rather than the master account. The cases reuse the existing
order request and cleanup helpers instead of duplicating order logic.

## Naming cleanup

Rename the private helper:

- `_market_limit_price` → `_market_price`

The existing `_market_order` helper continues to normalize public market
requests into IOC limit wire orders. `_market_price` describes the caller's
requested behavior; the IOC representation remains an internal detail.

Rename Info integration tests whose names contain more than four underscores:

| Current | Replacement |
|---|---|
| `test_spot_mid_price_uses_testnet_protocol_coin` | `test_hype_spot_mapping` |
| `test_purr_mid_price_preserves_named_pair` | `test_purr_spot_mapping` |
| `test_outcome_market_uses_spot_like_encoding` | `test_outcome_mapping` |
| `test_perps_at_open_interest_cap` | `test_open_interest_cap` |
| `test_mainnet_legacy_hype_alias_price_parity` | `test_hype_price_parity` |

The contract suite enforces the four-underscore maximum for functions in
`tests/integration/test_info.py`. Info endpoint coverage is based on actual AST
method calls rather than requiring the test name to copy the complete endpoint
method name.

## Test-first implementation and validation

The implementation proceeds through these red-green contracts:

1. Collection expects every common Info case with `mainnet` and `testnet` IDs
   and no opt-in deselection.
2. Availability-policy tests prove one delayed 429 retry, second-429 skip,
   TESTNET 5xx warning/skip, and MAINNET 5xx failure.
3. Market-mapping tests pin HYPE on both networks and mainnet PURR.
4. Naming contracts fail on the current long function names and endpoint-name
   coupling.
5. Offline SDK parity fails until both account-address configurations are
   represented.
6. The second live order-routing case fails collection until `sub_hl` exists.
7. The private-name test fails until `_market_price` replaces the old helper.

Final validation includes Ruff, sequential ty checks, the deterministic suite,
full dual-network Info integration, offline signing parity, both live testnet
vault-routing cases, Exchange post-run open-order/position cleanup checks, and
the package build. Any live secrets remain redacted from output and artifacts.
