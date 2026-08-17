# Signing benchmark

The overall signing benchmark values below are from a parity-gated `1.0.0rc1`
local CPU reference run. They are not network latency or exchange throughput.
See the detailed [benchmarks/README.md](https://github.com/owlyfi/async-hyperliquid/blob/main/benchmarks/README.md)
manual for the full methodology, parity gate, and per-operation results.

## Overall comparison

<!-- signing-benchmark:overall:start -->
| Library | Geometric-mean throughput | Relative to SDK |
|---|---:|---:|
| async-hyperliquid | 24,641 ops/s | 1.460x |
| Official SDK | 16,874 ops/s | 1.000x |
| CCXT | 803 ops/s | 0.0476x |

The geometric mean gives each of the five operations equal weight, preventing
the faster `action_hash` workload from dominating the score.
<!-- signing-benchmark:overall:end -->
