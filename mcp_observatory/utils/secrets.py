"""Fail-closed resolution for HMAC signing secrets.

``token/issuer.py``, ``token/verifier.py`` and ``proposal_commit/token.py``
each used to fall back to a hardcoded development secret (``dev-secret`` /
``dev-commit-secret``) whenever their environment variable was unset. That
default is public (it is in this file's git history and every clone of the
repo), so any deployment that forgot to set the real secret was silently
signing and verifying tokens with a key anyone can look up -- P3/P4 in
``docs/gate-properties.md`` assume the signing secret is uncompromised, and a
hardcoded fallback is a compromised secret by construction.

``resolve_secret`` makes that fallback opt-in instead of automatic: an unset
or known-default secret raises unless ``MCP_OBSERVATORY_ALLOW_DEV_SECRET=1``.
"""

from __future__ import annotations

import os

ALLOW_DEV_SECRET_ENV = "MCP_OBSERVATORY_ALLOW_DEV_SECRET"


class InsecureDefaultSecretError(RuntimeError):
    """Raised when a signing secret would fall back to a known-insecure default."""


def resolve_secret(explicit: str | None, *, env_var: str, dev_default: str, label: str) -> str:
    """Resolve a signing secret, refusing to silently use a development default.

    Returns ``explicit`` if given, else ``os.environ[env_var]``. If neither
    is set, or the resolved value equals ``dev_default`` (someone passed the
    known development secret on purpose, e.g. a copy-pasted example), the
    secret is treated as insecure and this raises unless
    ``MCP_OBSERVATORY_ALLOW_DEV_SECRET=1``, in which case ``dev_default`` is
    returned for local development, demos, and tests.
    """
    value = explicit if explicit is not None else os.getenv(env_var)
    if value is None or value == dev_default:
        if os.getenv(ALLOW_DEV_SECRET_ENV) == "1":
            return dev_default
        raise InsecureDefaultSecretError(
            f"{label} is unset (or set to the known development default). "
            f"Set {env_var} to a strong, private secret, or set "
            f"{ALLOW_DEV_SECRET_ENV}=1 for local development and tests only "
            "-- never in production."
        )
    return value
