---
name: debug-observability-review
description: Assess whether the change is diagnosable in remote or test environments through sufficient logging, tracing, metrics, and safe instrumentation. Trigger when local reproduction is hard or instrumentation changes are present.
---
# Debug and Observability Review

Input:
- analyzer output
- instrumentation-related snippets only

Check:
- trace and request correlation
- state transition visibility
- external call visibility
- secret leakage risk in logs
- excessive noisy logs
- debug flag safety

Output:
- missing observability
- unsafe instrumentation
- minimal instrumentation fix set
