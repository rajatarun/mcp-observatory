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


def _decode_canonical(segment: str) -> bytes:
    """Decode a base64url segment, accepting only its canonical spelling.

    The standard decoder is lenient: it ignores characters after the padding
    and non-alphabet characters, so ``token + "x"`` decoded to the same bytes
    as ``token`` and verified. Replay was still caught (the nonce lives in the
    payload), but a token then had unboundedly many accepted spellings, and
    anything keyed on the token string -- audit rows storing sha256(token) --
    could record the same authorisation under different hashes. Requiring the
    round-trip to reproduce the input makes the token string canonical.
    """
    raw = base64.urlsafe_b64decode(segment.encode("utf-8"))
    if base64.urlsafe_b64encode(raw).decode("utf-8") != segment:
        raise ValueError("non-canonical base64 segment")
    return raw


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
            payload_raw = _decode_canonical(payload_b64)
            sig = _decode_canonical(sig_b64)
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
