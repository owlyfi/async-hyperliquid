# Package and Test Layout Design

## Direction

Make package ownership and test discovery obvious without introducing a
generic `utils` junk drawer or changing the public API. Private implementation
modules move behind one `_internal` boundary, public protocol modules stay at
the package root, benchmarks live together, and test names rely on their
directory for domain context.

## Package boundaries

The package root remains the public map:

```text
async_hyperliquid/
├── client.py
├── exchange.py
├── info.py
├── constants.py
├── errors.py
├── types/
└── _internal/
    ├── encoding.py
    ├── exchange.py
    ├── http.py
    ├── info.py
    ├── metadata.py
    └── signing.py
```

`errors.py` stays at the root because its exception hierarchy is exported by
`async_hyperliquid.__init__`. `constants.py` stays at the root because it names
Hyperliquid protocol facts, not reusable algorithms. A `utils/` package is
rejected: it would hide ownership and invite unrelated helpers to accumulate.

Existing private modules move without compatibility shims because the RC1 is
unpublished and underscore-prefixed modules were never public API. Public
runtime modules import the new internal paths directly.

`_internal/exchange.py` owns pure amount conversion and strict Exchange action
response decoding. `_internal/info.py` owns Info JSON-shape validation,
cancellation-safe task waiting, and context-price decoding. `exchange.py` and
`info.py` retain client state, request construction, endpoint methods, metadata
lifecycle, signing/submission, and orchestration. No public method forwards
through a new wrapper.

## Benchmark layout

`scripts/client_hotpath_benchmark.py` becomes `benchmarks/hotpath.py`. Its unit
test becomes `tests/unit/test_hotpath.py`; README, CI, build documentation, and
historical executable-plan commands use the new path. The empty `scripts/`
directory disappears. `benchmarks/signing.py` remains the three-provider
parity benchmark.

## Test module naming

Magic `__init__.py` files are exempt. Every other test-side Python filename
with more than one underscore is shortened by removing domain context already
provided by its directory:

| Old | New |
|---|---|
| `tests/contracts/test_endpoint_coverage.py` | `tests/contracts/test_coverage.py` |
| `tests/oracle/test_signing_payload_parity.py` | `tests/oracle/test_signing.py` |
| `tests/typing/async_context_manager_usage.py` | `tests/typing/async_context.py` |
| `tests/typing/info_client_usage.py` | `tests/typing/info_client.py` |
| `tests/typing/test_public_api.py` | `tests/typing/test_api.py` |
| `tests/typing/test_v1_types.py` | `tests/typing/test_types.py` |
| `tests/unit/test_action_failures.py` | `tests/unit/test_actions.py` |
| `tests/unit/test_client_hotpath_benchmark.py` | `tests/unit/test_hotpath.py` |
| `tests/unit/test_close_positions.py` | `tests/unit/test_positions.py` |
| `tests/unit/test_exchange_client.py` | `tests/unit/test_exchange.py` |
| `tests/unit/test_info_client.py` | `tests/unit/test_info.py` |
| `tests/unit/test_live_test_config.py` | `tests/unit/test_integration.py` |
| `tests/unit/test_order_encoding.py` | `tests/unit/test_encoding.py` |
| `tests/unit/test_place_order.py` | `tests/unit/test_orders.py` |
| `tests/unit/test_signing_benchmark.py` | `tests/unit/test_benchmark.py` |
| `tests/unit/types/test_public_signatures.py` | `tests/unit/types/test_signatures.py` |
| `tests/unit/types/test_wire_types.py` | `tests/unit/types/test_wire.py` |

No test function is renamed merely to satisfy a filename rule. Function names
continue to describe the behavior they protect.

## Integration vocabulary and discovery

The API-wallet/subaccount client fixture is named `hl`; `master_hl` remains
distinct because it signs master-only actions. Within integration support,
`live_config.py`, `LiveMarkets`, `validate_live_credentials`, and
`validate_live_roles` become `config.py`, `Markets`, `validate_credentials`,
and `validate_roles`. Opt-in variables become `RUN_INFO_TESTS` and
`RUN_EXCHANGE_TESTS`; `RUN_DESTRUCTIVE_EXCHANGE_TESTS` remains explicit.

The global pytest marker expression is removed from `addopts`. It currently
causes all 60 Exchange cases to be deselected during VS Code collection. Tests
must always collect; runtime fixtures decide whether network execution is
enabled. The default run therefore reports integration tests as skipped rather
than pretending they do not exist. Mainnet remains a hard failure for Exchange
execution, credentials come only from `.env.local`, and destructive actions
retain a second explicit opt-in.

The repository gains a subprocess collection regression that runs pytest with
the repository's real configuration and asserts an Exchange node is collected.
This tests observable discovery behavior, not source text.

## Validation

- `pytest --collect-only tests/integration/exchange` succeeds without `-m` and
  lists all Exchange nodes.
- A plain deterministic suite performs no network calls; gated integration
  cases are visible as skips.
- Ruff covers `src tests benchmarks`.
- `ty` runs sequentially for `src`, each test domain, and `benchmarks`.
- The complete testnet Exchange suite runs from `.env.local` with explicit
  `RUN_EXCHANGE_TESTS=true RUN_DESTRUCTIVE_EXCHANGE_TESTS=true` and
  `IS_MAINNET=false` enforced by the fixture.
- A post-suite Info query reports zero residual open orders and positions.
- Public imports and official-SDK signing parity stay unchanged.

## Non-goals

- No generic `utils` package.
- No compatibility modules for private underscore imports.
- No public API rename.
- No change to Copycat or any other repository.
- No automatic network execution in CI without credentials.
