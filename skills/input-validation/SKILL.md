---
name: input-validation
description: Review parsing, schema validation, constraints, sanitization, and malformed-input handling. Trigger when new or changed input surfaces appear.
---
# Input Validation Review

Input:
- analyzer output
- input handling snippets only

Check:
- required fields
- schema enforcement
- boundary conditions
- malformed payload handling
- encoding and normalization surprises
- error messages that leak internals

Output:
- validation gaps
- risky malformed cases
- minimum fixes
