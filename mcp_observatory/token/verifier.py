"""Execution token verification with replay protection."""

from __future__ import annotations

import base64
import hmac
import json
from hashlib import sha256
from typing import Dict

from ..utils.secrets import resolve_secret
from ..utils.time import utc_now
from .types import VerificationResult


def _decode_canonical(segment: str) -> bytes:
    """Decode base64url accepting only the canonical spelling.

    The lenient decoder ignores bytes after padding, so ``token + "x"`` verified
    as ``token``. The token hash recorded on the span is sha256 over the string,
    so a malleable string lets one authorisation appear under many hashes.
    """
    raw = base64.urlsafe_b64decode(segment.encode("utf-8"))
    if base64.urlsafe_b64encode(raw).decode("utf-8") != segment:
        raise ValueError("non-canonical base64 segment")
    return raw


class TokenVerifier:
    """Verify signed execution tokens and bind them to tool invocation args."""

    def __init__(self, *, secret_key: str | None = None, replay_protection: bool = True) -> None:
        self._secret = resolve_secret(
            secret_key,
            env_var="MCP_OBSERVATORY_TOKEN_SECRET",
            dev_default="dev-secret",
            label="MCP_OBSERVATORY_TOKEN_SECRET",
        ).encode("utf-8")
        self._seen: Dict[str, int] = {}
        self._replay_protection = replay_protection

    def verify(self, token: str, *, tool_name: str, tool_args_hash: str) -> VerificationResult:
        try:
            payload_b64, sig_b64 = token.split(".", 1)
            payload_raw = _decode_canonical(payload_b64)
            sig = _decode_canonical(sig_b64)
        except Exception:
            return VerificationResult(False, "token_decode_failed")

        expected_sig = hmac.new(self._secret, payload_raw, sha256).digest()
        if not hmac.compare_digest(sig, expected_sig):
            return VerificationResult(False, "invalid_signature")

        try:
            payload = json.loads(payload_raw.decode("utf-8"))
        except Exception:
            return VerificationResult(False, "invalid_payload_json")

        now_ms = int(utc_now().timestamp() * 1000)
        exp = int(payload.get("expires_at", 0))
        if exp <= now_ms:
            return VerificationResult(False, "token_expired", payload=payload)

        if payload.get("tool_name") != tool_name:
            return VerificationResult(False, "tool_name_mismatch", payload=payload)

        if payload.get("tool_args_hash") != tool_args_hash:
            return VerificationResult(False, "tool_args_hash_mismatch", payload=payload)

        token_id = str(payload.get("token_id", ""))
        if self._replay_protection and token_id:
            self._gc(now_ms)
            if token_id in self._seen:
                return VerificationResult(False, "token_replay_detected", payload=payload)
            self._seen[token_id] = exp

        return VerificationResult(True, "ok", payload=payload)

    def _gc(self, now_ms: int) -> None:
        expired = [k for k, v in self._seen.items() if v <= now_ms]
        for k in expired:
            self._seen.pop(k, None)
