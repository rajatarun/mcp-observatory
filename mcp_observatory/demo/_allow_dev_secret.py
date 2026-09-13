"""Opt the bundled demos into the development signing secret, loudly.

The README documents ``python -m mcp_observatory.demo.run_demo`` and
``python examples/real_world_mcp_server.py`` as needing no configuration.
Since ``token/issuer.py``, ``token/verifier.py`` and
``proposal_commit/token.py`` now refuse a missing signing secret (see
``mcp_observatory.utils.secrets``), the demo entry points opt in on the
caller's behalf instead of that promise silently becoming false. Anything
that is not this bundled demo should set
``MCP_OBSERVATORY_TOKEN_SECRET`` / ``MCP_OBSERVATORY_COMMIT_SECRET``
instead of calling this.
"""

from __future__ import annotations

import os
import warnings

from ..utils.secrets import ALLOW_DEV_SECRET_ENV


def allow_dev_secret_for_demo() -> None:
    if os.environ.get(ALLOW_DEV_SECRET_ENV) == "1":
        return
    warnings.warn(
        "mcp_observatory demo: no MCP_OBSERVATORY_TOKEN_SECRET / "
        "MCP_OBSERVATORY_COMMIT_SECRET set -- using the library's built-in "
        "development secret so the demo runs with zero configuration. "
        "This is fine here and MUST NOT happen in production: set both "
        "environment variables to real secrets before deploying.",
        stacklevel=2,
    )
    os.environ[ALLOW_DEV_SECRET_ENV] = "1"
