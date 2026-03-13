---
name: operational-risk
description: Review retry storms, queue buildup, dependency failure amplification, timeouts, rate limits, rollout hazards, and job orchestration risk. Trigger when external systems or long-running workflows are involved.
---
# Operational Risk Review

Input:
- analyzer output
- operationally relevant snippets only

Check:
- retry amplification
- missing timeouts
- queue poison message behavior
- circuit breaker absence
- rollout coordination issues
- alerting and visibility gaps

Output:
- outage modes
- operational safeguards needed
- deploy readiness judgment
