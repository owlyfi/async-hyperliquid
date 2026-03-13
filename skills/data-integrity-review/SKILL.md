---
name: data-integrity-review
description: Review transactions, write ordering, deduplication, idempotency, partial failure, and consistency risk. Trigger when stateful writes, migrations, queues, or replayable events are involved.
---
# Data Integrity Review

Input:
- analyzer output
- write paths only

Check:
- partial writes
- missing transactions
- duplicate processing
- ordering assumptions
- replay safety
- compensation gaps

Output:
- integrity risks
- plausible failure sequence
- minimal integrity fix set
