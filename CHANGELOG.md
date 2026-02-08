# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
