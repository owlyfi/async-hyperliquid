---
name: red-team-review
description: Conduct adversarial review for trust-boundary violations, auth and authz flaws, replay issues, unsafe debug paths, injection, SSRF, and tenant isolation failures. Trigger for nearly all non-trivial code review.
---
# Red-Team Review

Input:
- analyzer output
- security-relevant snippets only

Assume:
- hostile input
- replayed events
- misconfigured flags
- partial failure
- careless operators

Check:
- auth/authz bypass
- injection vectors
- replayability
- secret leakage
- debug endpoint misuse
- internal API trust mistakes
- tenant isolation failures

Output:
- abuse scenario
- impact
- minimal mitigation
- block merge? yes/no
