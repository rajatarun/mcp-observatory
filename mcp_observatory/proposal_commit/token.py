"""Commit token signing and verification."""

from __future__ import annotations

import base64
import hmac
import json
import os
from dataclasses import dataclass
from hashlib import sha256
from time import time
from typing import Any
from uuid import uuid4


@dataclass(frozen=True)
class TokenIssueResult:
    token: str
    token_id: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class TokenVerifyResult:
    valid: bool
    reason: str
    payload: dict[str, Any] | None = None


class CommitTokenManager:
    """Issue and verify HMAC-SHA256 commit tokens."""

    def __init__(self, secret: str | None = None, ttl_seconds: int = 60) -> None:
        self.secret = (secret or os.getenv("MCP_OBSERVATORY_COMMIT_SECRET", "dev-commit-secret")).encode("utf-8")
        self.ttl_seconds = ttl_seconds

    def issue(
        self,
        *,
        proposal_id: str,
        tool_name: str,
        tool_args_hash: str,
        composite_score: float,
    ) -> TokenIssueResult:
        issued_at = int(time())
        token_payload = {
            "token_id": str(uuid4()),
            "proposal_id": proposal_id,
            "tool_name": tool_name,
            "tool_args_hash": tool_args_hash,
            "issued_at": issued_at,
            "expires_at": issued_at + self.ttl_seconds,
            "nonce": str(uuid4()),
            "composite_score": composite_score,
        }
        payload_raw = json.dumps(token_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        sig = hmac.new(self.secret, payload_raw, sha256).digest()
        token = f"{base64.urlsafe_b64encode(payload_raw).decode()}.{base64.urlsafe_b64encode(sig).decode()}"
        return TokenIssueResult(token=token, token_id=token_payload["token_id"], payload=token_payload)

    def verify(self, token: str) -> TokenVerifyResult:
        try:
            payload_b64, sig_b64 = token.split(".", 1)
            payload_raw = base64.urlsafe_b64decode(payload_b64.encode("utf-8"))
            sig = base64.urlsafe_b64decode(sig_b64.encode("utf-8"))
        except Exception:
            return TokenVerifyResult(valid=False, reason="bad_signature")

        expected = hmac.new(self.secret, payload_raw, sha256).digest()
        if not hmac.compare_digest(expected, sig):
            return TokenVerifyResult(valid=False, reason="bad_signature")

        try:
            payload = json.loads(payload_raw.decode("utf-8"))
        except Exception:
            return TokenVerifyResult(valid=False, reason="bad_signature")

        if int(payload.get("expires_at", 0)) <= int(time()):
            return TokenVerifyResult(valid=False, reason="expired", payload=payload)

        return TokenVerifyResult(valid=True, reason="ok", payload=payload)
