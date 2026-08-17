# Simplified Chinese Documentation Design

## Goal

Publish and continuously validate a Simplified Chinese (`zh_CN`) version of
the public documentation while keeping English RST/Markdown sources canonical.

## Architecture

Use Sphinx gettext catalogs under
`docs/locale/zh_CN/LC_MESSAGES/`. English source documents keep their current
paths and remain the only place where structure, directives, links, code
examples, and autodoc declarations are edited. Chinese `.po` files translate
the extracted narrative messages.

Configure `locale_dirs = ["locale/"]`, `gettext_compact = False`, and
`gettext_uuid = True`. Add `sphinx-intl` to the locked docs dependency group so
maintainers can extract and update catalogs consistently.

## Translation boundary

Translate all explanatory content in:

- the root landing page;
- Introduction and How-to pages;
- coin-name mapping and the migration guide;
- Project pages, except the canonical MIT license literal block;
- API Reference navigation and explanatory prose.

Keep Python class names, method names, type names, signatures, module paths,
code blocks, wire fields, and autodoc-generated content in English. Do not add
gettext literal-block targets. Missing API catalog entries deliberately fall
back to the canonical English text.

Use consistent terminology: Info API, Exchange API, API wallet, main account,
subaccount, vault, spot, perpetual, outcome, DEX, nonce, and builder remain in
English when translating them would make protocol terminology ambiguous.

## Build and hosting

Local and automated validation build both languages independently with warning
as error and network blocked:

- English output: `docs/_build/html/en/`
- Simplified Chinese output: `docs/_build/html/zh_CN/`

CI and release gates run both builds. Read the Docs uses the same repository and
configuration for two projects: the existing English parent and a Simplified
Chinese translation project linked through the Read the Docs Translations
setting. Repository work cannot create that external project, so an internal
runbook records the required administrative step.

## Maintenance workflow

Maintain translations with:

1. `sphinx-build -b gettext docs docs/_build/gettext`
2. `sphinx-intl update -p docs/_build/gettext -l zh_CN -d docs/locale`
3. edit only `docs/locale/zh_CN/LC_MESSAGES/*.po`
4. run both strict HTML builds and the package tests

Commit `.po` files. Do not commit generated `.pot`, `.mo`, gettext output, or
HTML output under `docs/_build/`.

## Validation

Tests exercise actual rendered artifacts. They require both English and
Simplified Chinese builds to finish offline without warnings, assert Chinese
content on representative narrative pages, preserve English API identifiers in
the Chinese API Reference, and retain the author-email privacy boundary. A
catalog coverage check requires a non-empty translation for every extracted
message in the selected narrative domains; API/autodoc fallback domains are
explicitly excluded.
