"""Fail-closed resolution of signing secrets (see mcp_observatory/utils/secrets.py).

The autouse fixture in conftest.py sets MCP_OBSERVATORY_ALLOW_DEV_SECRET=1 for
every test; these tests explicitly unset it to check the behaviour it exists
to opt out of.
"""

from __future__ import annotations

import pytest

from mcp_observatory.proposal_commit.token import CommitTokenManager
from mcp_observatory.token.issuer import TokenIssuer
from mcp_observatory.token.verifier import TokenVerifier
from mcp_observatory.utils.secrets import InsecureDefaultSecretError, resolve_secret


@pytest.mark.parametrize(
    "make",
    [
        lambda: TokenIssuer(),
        lambda: TokenVerifier(),
        lambda: CommitTokenManager(),
    ],
)
def test_unset_secret_raises_without_dev_secret_opt_in(monkeypatch, make) -> None:
    monkeypatch.delenv("MCP_OBSERVATORY_ALLOW_DEV_SECRET", raising=False)
    monkeypatch.delenv("MCP_OBSERVATORY_TOKEN_SECRET", raising=False)
    monkeypatch.delenv("MCP_OBSERVATORY_COMMIT_SECRET", raising=False)
    with pytest.raises(InsecureDefaultSecretError):
        make()


@pytest.mark.parametrize(
    "env_var,dev_default",
    [
        ("MCP_OBSERVATORY_TOKEN_SECRET", "dev-secret"),
        ("MCP_OBSERVATORY_COMMIT_SECRET", "dev-commit-secret"),
    ],
)
def test_explicit_known_default_also_raises(monkeypatch, env_var, dev_default) -> None:
    """Passing the known-default value on purpose is not a way around the check."""
    monkeypatch.delenv("MCP_OBSERVATORY_ALLOW_DEV_SECRET", raising=False)
    with pytest.raises(InsecureDefaultSecretError):
        resolve_secret(dev_default, env_var=env_var, dev_default=dev_default, label=env_var)


def test_unset_secret_allowed_with_opt_in(monkeypatch) -> None:
    monkeypatch.delenv("MCP_OBSERVATORY_TOKEN_SECRET", raising=False)
    monkeypatch.setenv("MCP_OBSERVATORY_ALLOW_DEV_SECRET", "1")
    issuer = TokenIssuer()
    assert issuer._secret == b"dev-secret"


def test_real_secret_never_needs_the_opt_in(monkeypatch) -> None:
    monkeypatch.delenv("MCP_OBSERVATORY_ALLOW_DEV_SECRET", raising=False)
    monkeypatch.setenv("MCP_OBSERVATORY_TOKEN_SECRET", "a-real-secret")
    issuer = TokenIssuer()
    assert issuer._secret == b"a-real-secret"
