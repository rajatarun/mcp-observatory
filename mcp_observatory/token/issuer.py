"""HMAC-backed execution token issuer."""

from __future__ import annotations

import base64
import hmac
import json
import os
from hashlib import sha256
from uuid import uuid4

from ..utils.time import utc_now
from .types import IssuedToken


class TokenIssuer:
    """Issue compact signed tokens for internal tool execution authorization."""

    def __init__(self, *, secret_key: str | None = None, ttl_ms: int = 30_000) -> None:
        self._secret = (secret_key or os.getenv("MCP_OBSERVATORY_TOKEN_SECRET", "dev-secret")).encode("utf-8")
        self.ttl_ms = ttl_ms

    def issue(
        self,
        *,
        trace_id: str,
        tool_name: str,
        tool_args_hash: str,
        decision: str,
        composite_risk_score: float,
    ) -> IssuedToken:
        issued_at = int(utc_now().timestamp() * 1000)
        payload = {
            "token_id": str(uuid4()),
            "trace_id": trace_id,
            "tool_name": tool_name,
            "tool_args_hash": tool_args_hash,
            "decision": decision,
            "composite_risk_score": composite_risk_score,
            "issued_at": issued_at,
            "expires_at": issued_at + self.ttl_ms,
            "nonce": str(uuid4()),
        }
        payload_raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        sig = hmac.new(self._secret, payload_raw, sha256).digest()
        token = f"{base64.urlsafe_b64encode(payload_raw).decode('utf-8')}.{base64.urlsafe_b64encode(sig).decode('utf-8')}"
        token_hash = sha256(token.encode("utf-8")).hexdigest()
        return IssuedToken(token=token, token_id=payload["token_id"], token_hash=token_hash, ttl_ms=self.ttl_ms, payload=payload)
