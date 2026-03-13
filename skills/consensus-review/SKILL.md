---
name: consensus-review
description: Resolve conflicts or ambiguity between multiple review skills and issue a final merge recommendation. Use this when skills disagree about severity or merge readiness.
---
# Review Consensus

Input:
- merged review report
- original skill outputs for disputed findings

Tasks:
1. Identify conflicts in severity, scope, or recommended action.
2. Prefer correctness, security, integrity, and rollback safety over convenience.
3. Decide final classification for disputed issues.
4. Produce a final merge decision:
   - yes
   - yes with follow-up
   - no

Output format:
```md
# Consensus Decision

Final merge decision: yes|yes with follow-up|no

Resolved conflicts:
- issue → final classification → why

Required actions:
- item
```
