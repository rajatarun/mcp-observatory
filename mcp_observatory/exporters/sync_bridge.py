"""Encrypted cloud sync bridge for ``SQLiteSpanExporter``.

Reads unflushed span batches from a local SQLite WAL database, encrypts them
with AES-256-GCM (32-byte key + fresh 12-byte random nonce per batch), and
delivers the JSON envelope over a pluggable transport (defaulting to stdlib
``urllib.request`` HTTP POST). Spans are marked flushed *only* when the
transport returns a 2xx acknowledgement.
"""

from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .sqlite import SQLiteSpanExporter

ENVELOPE_VERSION = 1
ENVELOPE_ALG = "AES-256-GCM"
KEY_BYTES = 32
NONCE_BYTES = 12

TransportFn = Callable[[dict[str, Any]], int | bool]


def _require_aesgcm():
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError as exc:
        raise RuntimeError(
            "cryptography is required for EncryptedSyncBridge; install mcp-observatory[sync]"
        ) from exc
    return AESGCM


def _validate_key(key: bytes) -> None:
    if not isinstance(key, (bytes, bytearray)) or len(key) != KEY_BYTES:
        raise ValueError(f"AES-256-GCM key must be exactly {KEY_BYTES} bytes")


def encrypt_spans(
    spans: list[dict[str, Any]],
    key: bytes,
    *,
    aad: bytes | None = None,
) -> dict[str, Any]:
    """Serialize *spans* to JSON and encrypt them into an AES-256-GCM envelope."""
    _validate_key(key)
    aesgcm_cls = _require_aesgcm()
    nonce = os.urandom(NONCE_BYTES)
    plaintext = json.dumps(spans, separators=(",", ":"), default=str).encode("utf-8")
    ciphertext = aesgcm_cls(bytes(key)).encrypt(nonce, plaintext, aad)
    return {
        "version": ENVELOPE_VERSION,
        "alg": ENVELOPE_ALG,
        "nonce_b64": base64.b64encode(nonce).decode("ascii"),
        "ciphertext_b64": base64.b64encode(ciphertext).decode("ascii"),
        "span_count": len(spans),
    }


def decrypt_envelope(
    envelope: dict[str, Any],
    key: bytes,
    *,
    aad: bytes | None = None,
) -> list[dict[str, Any]]:
    """Decrypt and verify an AES-256-GCM envelope produced by ``EncryptedSyncBridge``."""
    _validate_key(key)
    if envelope.get("alg") != ENVELOPE_ALG:
        raise ValueError(f"Unsupported envelope algorithm: {envelope.get('alg')!r}")
    if "nonce_b64" not in envelope or "ciphertext_b64" not in envelope:
        raise ValueError("Envelope missing required fields 'nonce_b64' or 'ciphertext_b64'")

    nonce = base64.b64decode(envelope["nonce_b64"])
    if len(nonce) != NONCE_BYTES:
        raise ValueError(f"Invalid nonce length: expected {NONCE_BYTES} bytes, got {len(nonce)}")
    ciphertext = base64.b64decode(envelope["ciphertext_b64"])

    aesgcm_cls = _require_aesgcm()
    plaintext = aesgcm_cls(bytes(key)).decrypt(nonce, ciphertext, aad)
    decoded = json.loads(plaintext.decode("utf-8"))
    if not isinstance(decoded, list):
        raise TypeError("Decrypted envelope payload is not a list of spans")
    return decoded


def make_urllib_transport(
    endpoint_url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: float = 10.0,
) -> TransportFn:
    """Create a stdlib ``urllib.request`` POST transport returning the HTTP status code."""

    def _post(envelope: dict[str, Any]) -> int:
        payload = json.dumps(envelope, separators=(",", ":")).encode("utf-8")
        req_headers = {"Content-Type": "application/json", **(headers or {})}
        req = urllib.request.Request(
            endpoint_url,
            data=payload,
            headers=req_headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return int(getattr(resp, "status", resp.getcode()))
        except urllib.error.HTTPError as exc:
            return int(exc.code)

    return _post


@dataclass(frozen=True)
class SyncBatchResult:
    """Outcome of a single ``EncryptedSyncBridge.sync_once()`` attempt."""

    ok: bool
    span_count: int
    flushed_count: int
    status_code: int | None = None
    error: str | None = None
    envelope: dict[str, Any] | None = None


class EncryptedSyncBridge:
    """Encrypts and syncs pending SQLite spans to a remote receiver."""

    def __init__(
        self,
        exporter: SQLiteSpanExporter,
        *,
        key: bytes,
        endpoint_url: str | None = None,
        transport: TransportFn | None = None,
        headers: dict[str, str] | None = None,
        timeout: float = 10.0,
        aad: bytes | None = None,
    ) -> None:
        _validate_key(key)
        if transport is None and not endpoint_url:
            raise ValueError("Either transport or endpoint_url must be provided")
        self._exporter = exporter
        self._key = bytes(key)
        self._aad = aad
        self._transport: TransportFn = (
            transport
            if transport is not None
            else make_urllib_transport(endpoint_url or "", headers=headers, timeout=timeout)
        )

    @staticmethod
    def decrypt_envelope(
        envelope: dict[str, Any],
        key: bytes,
        *,
        aad: bytes | None = None,
    ) -> list[dict[str, Any]]:
        return decrypt_envelope(envelope, key, aad=aad)

    def sync_once(self, *, limit: int = 100) -> SyncBatchResult:
        """Read up to *limit* pending spans, encrypt, post, and mark flushed on 2xx."""
        rows = self._exporter.pending(limit=limit)
        if not rows:
            return SyncBatchResult(ok=True, span_count=0, flushed_count=0, status_code=None)

        row_ids = [row_id for row_id, _ in rows]
        spans = [item for _, item in rows]
        envelope = encrypt_spans(spans, self._key, aad=self._aad)

        try:
            ack = self._transport(envelope)
        except Exception as exc:  # noqa: BLE001
            return SyncBatchResult(
                ok=False,
                span_count=len(spans),
                flushed_count=0,
                status_code=None,
                error=f"{type(exc).__name__}: {exc}",
                envelope=envelope,
            )

        if isinstance(ack, bool):
            succeeded = ack
            status_code = 200 if ack else None
        elif isinstance(ack, int):
            status_code = ack
            succeeded = 200 <= ack < 300
        else:
            succeeded = False
            status_code = None

        if succeeded:
            self._exporter.mark_flushed(row_ids)
            return SyncBatchResult(
                ok=True,
                span_count=len(spans),
                flushed_count=len(row_ids),
                status_code=status_code,
                envelope=envelope,
            )

        return SyncBatchResult(
            ok=False,
            span_count=len(spans),
            flushed_count=0,
            status_code=status_code,
            error=f"non-2xx transport acknowledgement: {ack!r}",
            envelope=envelope,
        )

    def sync_all(self, *, batch_size: int = 100, max_batches: int = 1000) -> list[SyncBatchResult]:
        """Drain pending spans in batches until empty or a transport failure occurs."""
        results: list[SyncBatchResult] = []
        for _ in range(max_batches):
            res = self.sync_once(limit=batch_size)
            if res.span_count == 0:
                break
            results.append(res)
            if not res.ok:
                break
        return results
