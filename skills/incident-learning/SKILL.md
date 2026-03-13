---
name: incident-learning
description: Turn incident postmortems into durable review lessons by mapping the failure to existing review skills, appending lessons files, and proposing new checks or new skills when needed.
---
# Incident Learning

Input:
- postmortem or incident analysis
- optional existing `.agent/incident-lessons.md`

Steps:
1. Extract the concrete failure pattern.
2. Identify why existing review or runtime safeguards missed it.
3. Map the failure to one or more existing review skills.
4. Append a concise durable lesson to:
   - repository `.agent/incident-lessons.md`, and/or
   - affected skill `references/incident-lessons.md`
5. If the failure pattern does not fit existing skills, propose a new skill.
6. Recommend a follow-up run of `$pipeline-review` on similar code paths.

Output format:
```md
## YYYY-MM-DD Incident title
- Failure pattern:
- Impact:
- Why review missed it:
- Skills to update:
- New checks:
- Need new skill? yes/no
```

Prefer updating references files over rewriting the main `SKILL.md` unless the core workflow changes.
