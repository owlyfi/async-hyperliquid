Installation
============

async-hyperliquid requires Python |minimum-python| or newer. This value is
derived from the package's ``Requires-Python`` constraint, |requires-python|,
when the documentation builds.

Install the latest release from PyPI:

.. code-block:: console

   python -m pip install async-hyperliquid

With uv:

.. code-block:: console

   uv add async-hyperliquid

Confirm that the intended interpreter sees the package:

.. code-block:: console

   python -c "import async_hyperliquid; print(async_hyperliquid.__all__)"

No credentials are needed for Info requests. Signed Exchange actions require
an Ethereum account signing key and its corresponding main account or approved
API-wallet relationship.
