# Documentation Navigation and Language Switch Design

## Goal

Make the published documentation entry points accurate and predictable: the
README must show the current PyPI release, all public documentation links must
resolve to the maintained Read the Docs build, the Furo brand title must be
concise, and readers must be able to switch between English and Simplified
Chinese from the top of the left navigation.

This design extends the previously approved Simplified Chinese documentation
architecture. English sources remain canonical, and committed
`docs/locale/zh_CN/LC_MESSAGES/*.po` files remain the only translated content.

## Root causes

- The Shields endpoint now returns `v1.0.0`, but the unchanged image URL can
  remain stale behind GitHub's image cache.
- README links mix the Read the Docs root redirect and `/en/latest/` paths.
  Explicit versioned paths are safer and easier to test.
- Sphinx derives the default Furo title as
  `<project> <release> documentation` because `html_title` is unset.
- The English Read the Docs project has no linked translation project, so Read
  the Docs cannot publish a Chinese language path or expose its native language
  metadata.

## Selected architecture

Use Read the Docs' native translation-project model for hosting and a small
Furo sidebar template for the visible language control.

- Keep `async-hyperliquid` as the English parent project.
- Create `async-hyperliquid-zh-cn` from the same GitHub repository, configure
  its language as Simplified Chinese, and link it as a Translation of the
  English parent.
- Publish the current repository state through `latest`. The immutable
  `v1.0.0` tag already backs `stable` and cannot contain this navigation fix;
  the next package release will naturally move `stable` to code containing it.
- Preserve the current document path when switching languages. For example,
  `.../en/latest/howto/orders.html` maps to
  `.../zh-cn/latest/howto/orders.html` and back.

This is preferred over building two trees inside one Read the Docs project,
which would bypass native translation/version metadata, and over a JavaScript-
only path rewrite, which could advertise a language that is not actually
published.

## Repository changes

### README and package metadata

- Keep the dynamic Shields PyPI endpoint, but append a cache key containing the
  exact `project.version` value. Each release commit therefore produces a new
  image URL while the displayed value still comes from PyPI.
- Point the documentation badge, overview link, API Reference link, migration
  guide link, and the `pyproject.toml` Documentation URL at explicit
  `https://async-hyperliquid.readthedocs.io/en/latest/` locations.
- Add contract tests tying the badge cache key to `project.version` and
  rejecting unversioned or obsolete documentation entry points.

### Sphinx and Furo

- Set `html_title = project`, producing the sidebar and mobile title
  `async-hyperliquid` without the version or `documentation` suffix.
- Add `templates_path = ["_templates"]` and a narrowly scoped Furo sidebar
  fragment directly after `sidebar/brand.html`.
- The fragment renders `English | 简体中文`, marks the current language with
  `aria-current="page"`, and uses ordinary anchors so it remains usable without
  JavaScript.
- Derive the hosted version from Read the Docs build metadata, with `latest` as
  the deterministic local fallback. Generate both language links from the
  current Sphinx `pagename` so nested pages retain their location.
- Retain Furo's standard brand, search, scroll boundaries, navigation, ethical
  ads, and variant selector. Add only the language fragment and minimal local
  CSS required for spacing and active-state clarity.

## External Read the Docs configuration

Create the Chinese project only after the repository changes are available on
`main`. Configure it with:

- repository: `https://github.com/owlyfi/async-hyperliquid.git`;
- default branch/version: `main` / `latest`;
- language: Simplified Chinese (`zh-cn` at the hosted URL boundary);
- configuration file: the repository-root `.readthedocs.yaml`;
- translation parent: `async-hyperliquid`.

Read the Docs builds each linked project separately. `docs/conf.py` maps
`READTHEDOCS_LANGUAGE=zh-cn` to Sphinx locale `zh_CN` and maps `en` to `en`;
local and CI commands continue to use the existing explicit
`-D language=zh_CN` contract, which takes precedence over the local fallback.

## Validation

Automated tests must prove:

- the README badge cache key equals the package version;
- every public documentation link uses the explicit English `latest` root;
- strict offline English and Chinese Sphinx builds succeed;
- both builds render the exact brand title `async-hyperliquid`;
- both builds render English and Simplified Chinese links for the same page;
- the active language is exposed accessibly;
- Chinese narrative text remains translated while API names and autodoc text
  remain in English.

Browser acceptance covers the root page and one nested page in both languages,
including desktop and mobile navigation. Online acceptance requires 200
responses for English and Chinese `latest` pages, a non-empty Translations API
relationship, correct cross-language targets, and no 404 during switching.

## Rollout and rollback

Land and validate the repository changes first, then push `main`, create/link
the Chinese Read the Docs project, and monitor both builds. Do not move the
immutable `v1.0.0` tag.

If the Chinese project cannot build, remove or hide the language fragment while
leaving the English link/title fixes in place. If the custom sidebar fragment
regresses Furo layout, remove that one fragment and rely temporarily on Read
the Docs' native translation UI; translation hosting remains independent.
