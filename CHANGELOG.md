# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Extend `scripts/client_hotpath_benchmark.py` with warm-cache batch-order and batch-cancel benchmarks so scheduler overhead is measured separately from network-latency wins.

### Changed
- Split metadata lifecycle responsibilities so shared `AsyncHyperliquid` instances still coalesce concurrent cold-start initialization, while the public `init_metas()` API remains an explicit refresh hook for long-lived clients.
- Use cached asset ids with a flatter direct-lookup fast path for warm-cache `get_mark_price`, batch order preparation, and batch cancel preparation so hot paths stop linearly rescanning metadata or paying extra helper-call overhead for local dictionary work.
- Simplify signing float formatting to trim fixed-point strings directly instead of normalizing through `Decimal`, while now rejecting non-finite values explicitly so invalid payloads fail deterministically before signing.

## [0.4.5] - 2026-03-27

### Added
- Add `get_mark_price(coin)` to fetch live `markPx` values for spot pairs, the primary perp dex, and builder-deployed perp dexs from the corresponding asset-context endpoints.
- Add live mainnet integration coverage for `get_mark_price`, including spot aliases, builder-deployed perp symbols, unsupported legacy symbol forms, and HYPE cross-quote parity checks against perp pricing.

### Changed
- Allow `InfoAPI.get_perp_meta_ctx` to target a specific perp dex via the optional `dex` request field.
- Document a code-level TODO in `init_metas` for future HIP-4 outcome asset/meta initialization, since outcome asset IDs use a separate encoding path from current perp and spot markets.

### Fixed
- Resolve spot `get_mark_price` lookups by the spot pair `index` returned in `spotMetaAndAssetCtxs`, so aliases and quoted spot pairs like `USDT0/USDC`, `USDE/USDC`, `USDH/USDC`, and `@107` read the correct live `markPx`.

## [0.4.4] - 2026-03-25

### Added
- Vendor repository-local review pipeline and routed review skills under `skills/` so the Reviewer workflow in `AGENTS.md` does not depend on user-level skill installation.
- Add `scripts/signing_benchmark.py` to compare cached EIP-712 template reuse, backend selection, and order batching against the legacy rebuild-on-every-call signing path with repeatable local benchmarks.
- Add `scripts/client_hotpath_benchmark.py` to measure metadata fan-out concurrency, warm-cache order rounding, and batch cancel asset-resolution throughput against legacy serial code paths.
- Add `coincurve` as a runtime dependency so `eth-account`/`eth-keys` can use the faster CoinCurve secp256k1 backend by default.
- Add `close_positions(coins)` so callers can close a selected set of positions through one batched market-order action instead of looping over `close_position`.

### Changed
- Allow `AsyncHyperliquid` to reuse a caller-provided `aiohttp` session and use a pooled connector with DNS caching for internally managed HTTP clients.
- Reuse cached EIP-712 signing templates for static `domain` and `types` payload sections to cut Python object churn on high-frequency signed requests.
- Prepare batch order payloads concurrently before signing so large `batch_place_orders` calls spend less time serially rounding assets and prices.
- Fetch base/spot metadata and per-DEX metadata concurrently in `get_metas`, `get_all_metas`, and `get_all_market_prices`, and resolve batch cancel asset ids in parallel instead of serially awaiting each lookup.

### Fixed
- Align the vendored review-pipeline skill metadata and `AGENTS.md` references with the existing user-level `pipeline-review` name to avoid mixed identifiers.
- Ensure signed actions use a per-client monotonic nonce generator so concurrent requests do not collide when multiple actions are submitted in the same millisecond.
- Redact signature material from debug request logs while keeping action type and request metadata visible for troubleshooting.
- Remove duplicate coin-name resolution from `get_coin_sz_decimals` so hot order-preparation paths only resolve cached metadata once per request.
- Keep `_init_spot_meta` resilient to malformed token indexes while caching quote-token aliases via `setdefault` for direct quote-token lookups.

## [0.4.3] - 2026-03-13

### Changed
- Document the Builder release workflow in `AGENTS.md`, including the requirement to create an explicit `vX.Y.Z` git tag for each versioned release.
- Refactor `AsyncHyperliquid` into focused internal client modules so metadata loading, read APIs, order flows, and signed account actions are easier to maintain without changing the public import path.

### Fixed
- Restore legacy helper re-exports from `async_hyperliquid.async_hyperliquid` so internal refactoring does not break downstream imports or monkeypatch-based tests.

## [0.4.2] - 2026-03-13

### Added
- Vendor repository-local Codex skills for `pua-debugging`, `systematic-debugging`, `verification-before-completion`, and `python-uv-workflow` under `skills/` so agent behavior does not depend on user-level skill installation.
- Add `ty` as a `dev` dependency so the repository-local `python-uv-workflow` verification path can run inside the project.

### Changed
- Require Builder workflow changes to update `CHANGELOG.md` in the same change set for every commit-worthy repository change.

### Fixed
- Resolve `ty` verification issues in `InfoAPI`, benchmark scripts, and abstraction integration tests so the repository-local `python-uv-workflow` checks pass in-project.

## [0.4.1] - 2026-03-11

### Changed
- Tighten `OrderBuilder.f` typing from `float` to `int` to match the encoded builder fee representation used by order payloads.

### Fixed
- Skip malformed spot metadata entries whose token indexes fall outside the returned token table, avoiding crashes when testnet returns unrecognized token references.
- Update the builder-fee integration order test to use a supported builder address and a liquid `BTC` test order payload.

## [0.4.0] - 2026-03-05

### Added
- Add dedicated order APIs: `place_market_order` and `place_typed_order` while keeping `place_order` for compatibility.
- Add order-type builder utilities and enums: `LimitTif`, `TriggerTpsl`, `limit_order_type`, and `trigger_order_type`.
- Add user abstraction query APIs: `InfoAPI.get_user_abstraction` and `AsyncHyperliquid.get_user_abstraction`.
- Add abstraction setting APIs: `AsyncHyperliquid.user_set_abstraction` and `AsyncHyperliquid.agent_set_abstraction`, including signing support (`USER_SET_ABSTRACTION_SIGN_TYPES` and `sign_user_set_abstraction_action`).

### Changed
- Reorganize tests into `tests/unit` and `tests/integration`, and split exchange integration tests into `test_exchange_orders.py` and `test_exchange_actions.py`.
- Improve `ensure_order_type` typing with `TypeGuard` helpers and use the limit-order builder path to avoid loose TypedDict narrowing.

### Deprecated
- Mark `user_dex_abstraction` and `agent_enable_dex_abstraction` as deprecated in favor of `user_set_abstraction` and `agent_set_abstraction`.

## [0.3.10] - 2026-02-08

### Added
- Add `user_set_abstraction` to `AsyncHyperliquid` plus signing support (`sign_user_set_abstraction_action`) and constants for the new action.
- Add `Abstraction` and `AgentAbstraction` typing literals.

### Changed
- Remove unnecessary `type: ignore` on `ExchangeAPI.address` assignment and `msgpack.packb` call; keep a targeted ignore for `ensure_order_type`.

## [0.3.9]

### Added
- Add `get_user_abstraction_state` to `InfoAPI` plus AsyncHyperliquid wrappers for user abstraction queries (`get_user_dex_abstraction`, `get_user_abstraction_state`).
- Add tests for `get_user_dex_abstraction` and `get_user_abstraction_state`.

### Changed
- Add targeted type-check ignores in `tests/test_info.py` and `utils/decorators.py` to quiet mypy/pyright warnings.

## [0.3.8] - 2026-01-27

### Fixed
- Corrected `dex_asset_offset` calculation for external perp DEXs (HIP-3) to align with mainnet asset IDs: changed formula to `PERP_DEX_OFFSET + (idx - 1) * 10000`.

## [0.3.7] - 2026-01-26

### Optimized
- `init_metas` in `AsyncHyperliquid` now only fetches metadata for DEXs explicitly specified in `perp_dexs`, reducing unnecessary HTTP calls.
- Corrected `dex_asset_offset` calculation to align with the full DEX list index, ensuring data consistency when fetching a subset of DEXs.

### Changed
- Updated `tests/conftest.py` to include common DEXs (`flx`, `vntl`, `xyz`) by default in the test client for better coverage.

## [0.3.5] - 2026-01-20

### Added
- Add `close_dex_positions` to close all positions in a specific DEX.
- Add `dexs` parameter to `get_all_positions` and `close_all_positions` for granular control.

### Changed
- Optimize request count by caching `perp_dexs` during initialization.
- Significant performance boost: `get_all_positions` now uses `asyncio.gather` for parallel fetching from multiple DEXs.
- `close_all_positions` and `close_position` now return `None` instead of raising `ValueError` when no positions are found, improving bot stability for long-running processes.
- `close_position` now only queries the specific DEX the coin belongs to, reducing Info API usage in multi-DEX environments.

### Fixed
- Correct parameter passing in `get_dex_positions` and `get_all_positions`.
- Ensure proper import of `get_coin_dex` and `asyncio`.

## [0.3.2] - 2025-12-01

### Added

- Support Enable HIP3 DEX abstraction: `user_dex_abstraction`
- Support Enable HIP3 DEX abstraction (agent): `agent_enable_dex_abstraction`

## [0.3.1] - 2025-11-28

### Fixed

- `get_perp_account_state` `dex` argument not passed

## [0.3.0] - 2025-11-27

### Added

- Support HIP-3: perp dexs
- Add `AsyncHyperliquid` class to encapsulate additional functionality
- Introduce `get_all_metas` and `get_mid_price` methods to `AsyncHyperliquid` for improved meta data handling
- Add utility function `get_leverages_from_positions` to calculate leverage from positions
- Refactor `AccountState` to include `dexs` for better state management

### Changed

- Bump version to 0.3.0
- Refactor payloads in `AsyncAPI` and `InfoAPI` to use a consistent naming convention
- Update existing methods to include return type annotations and enhanced docstrings for clarity
- Refactor tests to consistently use `AsyncHyperliquid` instead of `AsyncHyper` for improved clarity and maintainability
- Update `conftest.py` to load environment variables more efficiently
- Update methods to use `get_mid_price` for price calculations

### Removed

- Remove deprecated `_slippage_price` method from `AsyncHyperliquid`

### Enhanced

- Ensure all test functions are fully annotated and contain docstrings for better documentation
- Update tests to cover new functionality and ensure comprehensive coverage

## [0.2.6] - 2025-10-31

### Changed

- Refactor: integrate the `vault` and `expire` arguments into class attribute (2025-10-31)

## [0.2.5] - 2025-08-22

### Fixed

- Update meta cache if coin not found to ensure works for new list coin

## [0.2.4] - 2025-08-11

### Added

- Support transfer between accounts
- Support transfer between perpetual and spot
- Support transfer between perpetual and vaults
- Support transfer HYPE between spot and staking
- Support withdraw
- Support token delegation
- Support approve agent wallet (api wallet)
- Support convert single user to multi-sig user

## [0.2.3] - 2025-08-07

### Added

- Support to enable/disable EVM big block for HyperEVM smart contract deploy (2025-08-05)

### Changed

- Refactor: Change project layout from 'flat layout' to 'src layout' (2025-08-07)
- Integrate `uv` and add Hyperliquid EVM client (2025-08-07)

### Updated

- Update aiohttp 3.11.13 -> 3.12.15 (2025-08-02)

## [0.2.2] - 2025-07-24

### Fixed

- Strip '.0' for sz in place_twap (2025-07-24)

## [0.2.1] - 2025-07-17

### Added

- Support cancel order by cloid (2025-07-17)

## [0.2.0] - 2025-07-16

### Added

- Support place twap and cancel twap (2025-07-16)
- Support modify order (2025-07-16)

## [0.1.27] - 2025-07-14

### Fixed

- Remove redundancy get_coin_name in canceling (2025-07-14)
- Remove customized coin symbols in metas to avoid conflict (2025-07-14)

## [0.1.26] - 2025-07-02

### Fixed

- Round px properly with tick and lot size (2025-07-02)

## [0.1.20] - 2025-06-30

### Changed

- Deprecate _slippage_price, add _round_sz_px (2025-06-30)
- Unify argument name for orders: limit_px -> px, reduce_only -> ro (2025-06-30)

## [0.1.19] - 2025-06-29

### Added

- Support place TP/SL orders in place_order (2025-06-29)
- Add batch_place_orders to aggregate multiple orders into one request (2025-06-29)
- Add batch_cancel_orders to make cancels more efficient (2025-06-29)
- Use batch_place_orders in close_all_positions (2025-06-29)
- Test for batching (batch_place_orders and batch_cancel_orders) (2025-06-29)

### Fixed

- Do not add builder into OrderAction if builder is None (2025-06-29)

### Changed

- Use modern typing (python 3.10 and above) (2025-06-29)
- Comprehensive for cancel_orders (2025-06-29)
- Use more generic way in tests (2025-06-29)

### Enhanced

- Init_metas if coin not found in self.coin_names at the first time (2025-06-29)

## [0.1.18] - 2025-06-15

### Fixed

- Fix typo in ClearinghouseState (2025-06-15)

### Changed

- Remove commented codes cause not use anymore (2025-06-03)
- Add USD transfer functionalities (2025-06-03)
- Enhance type annotations and improve error handling in AsyncAPI and AsyncHyper classes (2025-06-03)

## [0.1.17] - 2025-03-30

### Added

- Add spot account state and perp account state (2025-03-30)
- Retrieve user latest ledgers (deposit, withdraw, transfer) (2025-03-26)
- Add Order types for better type hints (2025-03-18)
- Support retrieve user's portfolio (2025-03-17)
- Support get market price for all coins (2025-03-17)
- Support get coin symbol via it's name, mainly for spot coin (2025-03-16)
- Support for get account state (2025-03-15)

### Fixed

- Wrong return type for latest fundings (2025-03-26)
- Typo for get_order_status return type (2025-03-18)
- Can not get the spot coin name with it's symbols (2025-03-17)
- get_coin_symbol error with coin name for spot (2025-03-16)
- Remove un-necessary argument for market price (2025-03-15)

## [0.1.2] - 2025-03-15

### Added

- Support close all positions (2025-03-15)
- Support cancel orders (2025-03-15)

### Changed

- Change name to async-hyperliquid (2025-03-14)

## [0.1.0] - 2025-03-14

### Added

- Initial commit with basic functionality (2025-03-14)
- Project url metas for PyPI (2025-03-14)
- Pre-commit configuration (2025-03-14)

### Fixed

- Wrong test arguments for update_leverage (2025-03-14)
- Signing error for place order (2025-03-14)

### Changed

- Ignore poetry build stuffs (2025-03-14)
- Ignore test cache files (2025-03-14)
