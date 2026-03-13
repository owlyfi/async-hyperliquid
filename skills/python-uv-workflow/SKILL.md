---
name: python-uv-workflow
description: Use when working in a Python project that already uses uv, or when the user explicitly asks to bootstrap or standardize a Python project on uv. In those cases, ensure ruff and ty are present as dev dependencies and after Python code changes run `uv run ruff format`, `uv run ruff check`, and `uv run ty check`.
---

# Python UV Workflow

## When to use

Use this skill only when one of these is true:
- the repository already uses `uv` for Python package or task management
- the user explicitly asks to bootstrap, migrate, or standardize a Python project on `uv`

Typical examples:
- editing Python code in a repo that already has `uv.lock`
- updating `pyproject.toml` in a repo that already documents `uv`
- adding `ruff` or `ty` to a project the user wants standardized on `uv`

Do not use this skill for arbitrary Python repositories that already standardize on Poetry, Hatch, PDM, `pip-tools`, or another toolchain unless the user explicitly asks to move them to `uv`.

## Core rules

1. Do not change a Python repository's package manager just because it contains Python files.
2. Use this workflow only for repos that already use `uv`, or after the user explicitly asks to standardize on `uv`.
3. If `uv` is required for the task but is not installed on the machine, install it before doing Python package or task management:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

4. Within a `uv`-managed project, use `ruff` and `ty` for checks.
5. If either tool is missing from that `uv`-managed project, add it as a dev dependency:

```bash
uv add --dev ruff
uv add --dev ty
```

6. After every Python code change in a `uv`-managed project, run these commands from the project root:

```bash
uv run ruff format
uv run ruff check
uv run ty check
```

Do not claim the Python work is done until all three commands have been run and their results checked.

## Workflow

1. Confirm you are in the correct Python project root.
2. Determine whether the repository already uses `uv`, or whether the user explicitly asked to standardize it on `uv`.
3. If neither is true, do not apply this skill and do not mutate the project's toolchain.
4. If `uv` is required for the task but missing on the machine, install it.
5. If `ruff` or `ty` is missing from the `uv`-managed project, add the missing dev dependency with `uv add --dev`.
6. Make the smallest necessary code change.
7. Run:
   - `uv run ruff format`
   - `uv run ruff check`
   - `uv run ty check`
8. Read the output before reporting success.

## Guardrails

- Prefer `uv` commands over `pip`, `pipenv`, or ad hoc virtualenv management only when the repository already uses `uv`, or when the user has explicitly asked to standardize on `uv`.
- Do not install `uv` or add `ruff`/`ty` to a repo that uses another Python toolchain unless the user explicitly asked for that migration.
- Do not skip `ty check` just because formatting or linting passed.
- If one of the commands fails, report the failure and fix it before closing the task when possible.
- If the project is not actually Python-based, do not force this workflow.
