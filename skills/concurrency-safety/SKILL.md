---
name: concurrency-safety
description: Review for race conditions, lock ordering problems, retry interactions, shared mutable state, and async correctness. Trigger for queues, workers, async flows, streaming, and shared state changes.
---
# Concurrency Safety Review

Input:
- analyzer output
- async or stateful snippets only

Check:
- read-modify-write races
- idempotency under retries
- lock misuse
- ordering assumptions
- unbounded fan-out
- hidden shared mutable state

Output:
- concurrency hazards
- exploit or failure mode
- smallest safe fix
