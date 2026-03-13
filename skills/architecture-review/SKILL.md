---
name: architecture-review
description: Review architecture quality, layering, cohesion, ownership boundaries, and domain leakage. Trigger when changes add modules, alter structure, or cross service boundaries.
---
# Architecture Review

Input:
- analyzer output
- architecture-relevant files only

Check:
- layering violations
- domain leakage
- ownership confusion
- tight coupling
- unnecessary cross-module dependencies

Output:
- major architectural concerns
- why they matter
- smallest structural fix
