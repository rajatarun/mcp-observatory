"""Local audit query engine and tamper-evident SHA-256-chained bundle export.

Reads spans persisted by ``SQLiteSpanExporter`` and produces offline-verifiable
``audit-bundle-v1`` bundles in JSONL or CSV format.
"""

from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

AUDIT_BUNDLE_SCHEMA = "audit-bundle-v1"
GENESIS_HASH = "0" * 64
CSV_COLUMNS = [
    "seq",
    "prev_hash",
    "record_hash",
    "timestamp",
    "tool_name",
    "status",
    "risk_score",
    "span_json",
]


def _parse_iso_utc(ts: Any) -> datetime | None:
    if not isinstance(ts, str) or not ts.strip():
        return None
    raw = ts.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _derive_status(item: dict[str, Any]) -> str:
    explicit = item.get("status")
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip().lower()
    decision = str(item.get("policy_decision") or "").strip().lower()
    if item.get("error") or decision == "error":
        return "error"
    if item.get("gate_blocked") is True or decision in {"block", "blocked", "deny", "denied"}:
        return "blocked"
    return "ok"


def _extract_risk_score(item: dict[str, Any]) -> float | None:
    scores: list[float] = []
    for field in ("composite_risk_score", "hallucination_risk_score", "risk_score"):
        val = item.get(field)
        if isinstance(val, (int, float)) and not isinstance(val, bool):
            scores.append(float(val))
    if not scores:
        return None
    return scores[0]


def _canonical_span_json(span: dict[str, Any]) -> str:
    return json.dumps(span, sort_keys=True, separators=(",", ":"), default=str)


def _compute_record_hash(prev_hash: str, seq: int, canonical_span: str) -> str:
    payload = f"{prev_hash}:{seq}:{canonical_span}".encode()
    return hashlib.sha256(payload).hexdigest()


def _manifest_path_for(bundle_path: Path) -> Path:
    return Path(f"{bundle_path}.manifest.json")


class AuditQueryEngine:
    """Query and export tamper-evident audit bundles from a SQLiteSpanExporter DB."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)

    def _connect(self) -> sqlite3.Connection:
        if not self.db_path.is_file():
            raise FileNotFoundError(f"SQLite database not found: {self.db_path}")
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def query_spans(
        self,
        *,
        tool_name: str | None = None,
        status: str | None = None,
        min_risk: float | None = None,
        since_iso: str | None = None,
        until_iso: str | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        """Query spans matching the supplied filters in chronological order."""
        if limit < 0:
            raise ValueError("limit must be non-negative")

        since_dt = _parse_iso_utc(since_iso) if since_iso is not None else None
        if since_iso is not None and since_dt is None:
            raise ValueError(f"Invalid since_iso timestamp: {since_iso!r}")

        until_dt = _parse_iso_utc(until_iso) if until_iso is not None else None
        if until_iso is not None and until_dt is None:
            raise ValueError(f"Invalid until_iso timestamp: {until_iso!r}")

        wanted_status = status.strip().lower() if isinstance(status, str) and status.strip() else None

        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT timestamp, item_json FROM observatory_spans ORDER BY timestamp ASC, id ASC"
            ).fetchall()
        finally:
            conn.close()

        results: list[dict[str, Any]] = []
        for row in rows:
            if len(results) >= limit:
                break
            try:
                item = json.loads(row["item_json"])
            except json.JSONDecodeError:
                continue
            if not isinstance(item, dict):
                continue

            if tool_name is not None and item.get("tool_name") != tool_name:
                continue

            if wanted_status is not None:
                derived = _derive_status(item)
                decision = str(item.get("policy_decision") or "").strip().lower()
                explicit = str(item.get("status") or "").strip().lower()
                if wanted_status not in {derived, decision, explicit}:
                    continue

            if min_risk is not None:
                risk = _extract_risk_score(item)
                if risk is None or risk < float(min_risk):
                    continue

            if since_dt is not None or until_dt is not None:
                span_ts = _parse_iso_utc(
                    item.get("timestamp") or item.get("start_time") or row["timestamp"]
                )
                if span_ts is None:
                    continue
                if since_dt is not None and span_ts < since_dt:
                    continue
                if until_dt is not None and span_ts > until_dt:
                    continue

            results.append(item)

        return results

    def export_audit_bundle(
        self,
        output_path: str | Path,
        *,
        fmt: str = "jsonl",
        **filters: Any,
    ) -> dict[str, Any]:
        """Export matching spans with a SHA-256 hash chain and ``audit-bundle-v1`` manifest."""
        normalized_fmt = fmt.strip().lower()
        if normalized_fmt not in {"jsonl", "csv"}:
            raise ValueError(f"Unsupported export format {fmt!r}; expected 'jsonl' or 'csv'")

        spans = self.query_spans(**filters)
        out_path = Path(output_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        prev_hash = GENESIS_HASH
        chained_records: list[dict[str, Any]] = []
        for seq, span in enumerate(spans):
            canonical = _canonical_span_json(span)
            record_hash = _compute_record_hash(prev_hash, seq, canonical)
            chained_records.append(
                {
                    "seq": seq,
                    "prev_hash": prev_hash,
                    "record_hash": record_hash,
                    "span": span,
                    "_canonical_span": canonical,
                }
            )
            prev_hash = record_hash

        if normalized_fmt == "jsonl":
            with out_path.open("w", encoding="utf-8", newline="\n") as fh:
                for rec in chained_records:
                    line_obj = {
                        "seq": rec["seq"],
                        "prev_hash": rec["prev_hash"],
                        "record_hash": rec["record_hash"],
                        "span": rec["span"],
                    }
                    fh.write(json.dumps(line_obj, sort_keys=True, separators=(",", ":"), default=str))
                    fh.write("\n")
        else:
            with out_path.open("w", encoding="utf-8", newline="") as fh:
                writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
                writer.writeheader()
                for rec in chained_records:
                    span = rec["span"]
                    risk = _extract_risk_score(span)
                    writer.writerow(
                        {
                            "seq": rec["seq"],
                            "prev_hash": rec["prev_hash"],
                            "record_hash": rec["record_hash"],
                            "timestamp": span.get("timestamp") or span.get("start_time") or "",
                            "tool_name": span.get("tool_name") or "",
                            "status": _derive_status(span),
                            "risk_score": "" if risk is None else str(risk),
                            "span_json": rec["_canonical_span"],
                        }
                    )

        applied_filters = {k: v for k, v in filters.items() if v is not None}
        manifest: dict[str, Any] = {
            "schema": AUDIT_BUNDLE_SCHEMA,
            "record_count": len(chained_records),
            "chain_head_sha256": prev_hash,
            "exported_at": datetime.now(UTC).isoformat(),
            "format": normalized_fmt,
            "filters": applied_filters,
        }
        manifest_path = _manifest_path_for(out_path)
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return manifest


def _detect_format(path: Path, manifest: dict[str, Any] | None) -> str:
    if isinstance(manifest, dict) and manifest.get("format") in {"jsonl", "csv"}:
        return str(manifest["format"])
    if path.suffix.lower() == ".csv":
        return "csv"
    return "jsonl"


def verify_audit_bundle(bundle_path: str | Path) -> tuple[bool, list[str]]:
    """Verify a JSONL or CSV ``audit-bundle-v1`` export offline.

    Recomputes the SHA-256 hash chain across every record and validates against
    the sidecar ``<bundle_path>.manifest.json`` when present, detecting any
    modified, reordered, inserted, or deleted line.
    """
    path = Path(bundle_path)
    errors: list[str] = []

    if not path.is_file():
        return False, [f"Audit bundle file not found: {path}"]

    manifest_path = _manifest_path_for(path)
    manifest: dict[str, Any] | None = None
    if manifest_path.is_file():
        try:
            loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
            if not isinstance(loaded, dict):
                errors.append("Manifest JSON is not an object")
            else:
                manifest = loaded
                if manifest.get("schema") != AUDIT_BUNDLE_SCHEMA:
                    errors.append(
                        f"Unexpected manifest schema: {manifest.get('schema')!r} "
                        f"(expected {AUDIT_BUNDLE_SCHEMA!r})"
                    )
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"Failed to parse sidecar manifest {manifest_path}: {exc}")

    fmt = _detect_format(path, manifest)
    expected_prev = GENESIS_HASH
    record_count = 0

    if fmt == "jsonl":
        raw_lines = path.read_text(encoding="utf-8").splitlines()
        for line_no, raw_line in enumerate(raw_lines, start=1):
            if not raw_line.strip():
                errors.append(f"Line {line_no}: unexpected blank line")
                continue
            try:
                obj = json.loads(raw_line)
            except json.JSONDecodeError as exc:
                errors.append(f"Line {line_no}: invalid JSON ({exc})")
                continue
            if not isinstance(obj, dict):
                errors.append(f"Line {line_no}: record must be a JSON object")
                continue

            seq = obj.get("seq")
            prev_hash = obj.get("prev_hash")
            record_hash = obj.get("record_hash")
            span = obj.get("span")

            if seq != record_count:
                errors.append(
                    f"Line {line_no}: sequence mismatch (expected {record_count}, got {seq!r})"
                )
            if prev_hash != expected_prev:
                errors.append(
                    f"Line {line_no}: prev_hash mismatch (expected {expected_prev}, got {prev_hash!r})"
                )
            if not isinstance(span, dict):
                errors.append(f"Line {line_no}: missing or invalid 'span' object")
                record_count += 1
                if isinstance(record_hash, str):
                    expected_prev = record_hash
                continue

            canonical = _canonical_span_json(span)
            computed = _compute_record_hash(expected_prev, record_count, canonical)
            if record_hash != computed:
                errors.append(
                    f"Line {line_no}: record_hash mismatch (expected {computed}, got {record_hash!r})"
                )
            expected_prev = record_hash if isinstance(record_hash, str) else computed
            record_count += 1
    elif fmt == "csv":
        with path.open("r", encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            if reader.fieldnames != CSV_COLUMNS:
                errors.append(
                    f"CSV header mismatch (expected {CSV_COLUMNS}, got {reader.fieldnames})"
                )
                return False, errors

            for row_no, row in enumerate(reader, start=2):
                try:
                    seq = int(row["seq"])
                except (TypeError, ValueError):
                    errors.append(f"Row {row_no}: invalid seq {row.get('seq')!r}")
                    continue

                prev_hash = row.get("prev_hash") or ""
                record_hash = row.get("record_hash") or ""

                if seq != record_count:
                    errors.append(
                        f"Row {row_no}: sequence mismatch (expected {record_count}, got {seq})"
                    )
                if prev_hash != expected_prev:
                    errors.append(
                        f"Row {row_no}: prev_hash mismatch (expected {expected_prev}, got {prev_hash!r})"
                    )

                raw_span = row.get("span_json") or ""
                try:
                    span = json.loads(raw_span)
                except json.JSONDecodeError as exc:
                    errors.append(f"Row {row_no}: invalid span_json ({exc})")
                    record_count += 1
                    expected_prev = record_hash
                    continue

                if not isinstance(span, dict):
                    errors.append(f"Row {row_no}: span_json must decode to an object")
                    record_count += 1
                    expected_prev = record_hash
                    continue

                # Also verify denormalized CSV summary columns match span_json.
                expected_ts = str(span.get("timestamp") or span.get("start_time") or "")
                expected_tool = str(span.get("tool_name") or "")
                expected_status = _derive_status(span)
                risk = _extract_risk_score(span)
                expected_risk = "" if risk is None else str(risk)
                if (
                    (row.get("timestamp") or "") != expected_ts
                    or (row.get("tool_name") or "") != expected_tool
                    or (row.get("status") or "") != expected_status
                    or (row.get("risk_score") or "") != expected_risk
                ):
                    errors.append(f"Row {row_no}: CSV summary columns diverge from span_json")

                canonical = _canonical_span_json(span)
                computed = _compute_record_hash(expected_prev, record_count, canonical)
                if record_hash != computed:
                    errors.append(
                        f"Row {row_no}: record_hash mismatch (expected {computed}, got {record_hash!r})"
                    )
                expected_prev = record_hash or computed
                record_count += 1
    else:
        errors.append(f"Unsupported bundle format: {fmt!r}")

    if manifest is not None:
        expected_count = manifest.get("record_count")
        expected_head = manifest.get("chain_head_sha256")
        if expected_count != record_count:
            errors.append(
                f"Manifest record_count mismatch (expected {expected_count}, observed {record_count})"
            )
        if expected_head != expected_prev:
            errors.append(
                f"Manifest chain_head_sha256 mismatch (expected {expected_head}, observed {expected_prev})"
            )

    return len(errors) == 0, errors
