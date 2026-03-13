---
name: blast-radius-analysis
description: Analyze impact scope, shared-code risk, multi-service effects, and rollout surface area. Trigger when changes touch shared modules, config, migrations, or multiple systems.
---
# Blast Radius Analysis

Input:
- analyzer output
- `.agent/state.md` if present

Check:
- shared modules touched
- config surface changes
- infra or schema coupling
- public interfaces affected
- deployment coordination risk

Output:
- blast radius: low|medium|high
- main spread vectors
- containment suggestions
