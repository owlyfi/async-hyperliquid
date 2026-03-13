---
name: rollback-safety
description: Verify that a change can be safely rolled back, especially around migrations, state changes, feature flags, and backward compatibility. Trigger for almost all deployable changes.
---
# Rollback Safety Review

Input:
- analyzer output
- stateful code paths only when needed

Check:
- irreversible migrations
- incompatible schema or API transitions
- one-way state mutations
- bad flag defaults
- missing rollback notes

Output:
- rollback blockers
- rollback caveats
- minimum rollback-safe fix set
- safe-to-merge? yes/no
