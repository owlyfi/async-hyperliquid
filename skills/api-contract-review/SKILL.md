---
name: api-contract-review
description: Review API compatibility, schema evolution, versioning, response semantics, and client impact. Trigger when public contracts or exported models change.
---
# API Contract Review

Input:
- analyzer output
- contract-related files only

Check:
- backward compatibility
- versioning expectations
- field removal or semantic drift
- generated client impact
- docs/schema mismatch

Output:
- contract-breaking risks
- migration guidance
- compatibility-preserving fix
