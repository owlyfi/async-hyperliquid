# Project About and License Design

## Goal

Add clear author and license information to the public Read the Docs site
without publishing the author's email address.

## Public structure

- `docs/project/about.rst` identifies the project author as `Yuki`, links to
  the GitHub repository, and points users to the repository issue tracker.
- `docs/project/license.rst` identifies the project as MIT licensed, includes
  the repository's canonical `LICENSE` text with Sphinx `literalinclude`, and
  links to the canonical license file.
- `docs/project/index.rst` lists About, License, coin-name mapping, and the
  migration guide in its toctree.

## Source of truth and privacy

`pyproject.toml` remains the source of truth for the author name and license
identifier. `LICENSE` remains the canonical legal text. Public documentation
must not contain `yuqi.lyle@gmail.com` or any other author email address.

## Validation

The existing offline, warning-as-error Sphinx test checks the generated About
and License HTML, including `Yuki`, `MIT License`, navigation output, and the
absence of the author email from the complete rendered site.
