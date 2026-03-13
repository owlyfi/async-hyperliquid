---
name: performance-regression
description: Review performance risk around hot paths, loops, caching, database access, serialization, blocking operations, and memory use. Trigger when the change touches throughput or latency-sensitive logic.
---
# Performance Regression Review

Input:
- analyzer output
- hot-path snippets only

Check:
- accidental O(n^2) behavior
- N+1 access patterns
- blocking I/O in loops
- cache invalidation mistakes
- large allocation or serialization churn

Output:
- likely regressions
- severity
- cheap mitigation options
