"""Local CLI inspector for MCP Observatory SQLite span databases."""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


def _parse_iso(ts: Any) -> datetime | None:
    if not isinstance(ts, str) or not ts:
        return None
    normalized = ts[:-1] + "+00:00" if ts.endswith("Z") else ts
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def _extract_latency_ms(item: dict[str, Any]) -> float | None:
    for field in ("latency_ms", "duration_ms"):
        val = item.get(field)
        if isinstance(val, (int, float)) and not isinstance(val, bool) and val >= 0:
            return float(val)
    start_dt = _parse_iso(item.get("start_time"))
    end_dt = _parse_iso(item.get("end_time"))
    if start_dt is not None and end_dt is not None:
        if (start_dt.tzinfo is None) != (end_dt.tzinfo is None):
            start_dt = start_dt.replace(tzinfo=None)
            end_dt = end_dt.replace(tzinfo=None)
        delta_ms = (end_dt - start_dt).total_seconds() * 1000.0
        if delta_ms >= 0:
            return delta_ms
    return None


def _percentile(sorted_values: list[float], pct: float) -> float | None:
    """Compute linear-interpolated percentile (0..100) over sorted values."""
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return round(sorted_values[0], 3)
    rank = (pct / 100.0) * (len(sorted_values) - 1)
    lo = math.floor(rank)
    hi = math.ceil(rank)
    if lo == hi:
        return round(sorted_values[lo], 3)
    weight = rank - lo
    val = sorted_values[lo] * (1.0 - weight) + sorted_values[hi] * weight
    return round(val, 3)


def compute_sqlite_stats(db_path: str | Path) -> dict[str, Any]:
    """Compute summary statistics from a ``SQLiteSpanExporter`` database."""
    path = Path(db_path)
    if not path.is_file():
        raise FileNotFoundError(f"SQLite database not found: {path}")

    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT flushed, item_json FROM observatory_spans ORDER BY id ASC"
        ).fetchall()
    finally:
        conn.close()

    total = len(rows)
    pending = 0
    flushed = 0
    errors = 0
    blocked = 0
    latencies: list[float] = []

    for row in rows:
        if int(row["flushed"]) == 0:
            pending += 1
        else:
            flushed += 1

        try:
            item = json.loads(row["item_json"])
        except json.JSONDecodeError:
            continue

        decision = str(item.get("policy_decision") or "").lower()
        status = str(item.get("status") or "").lower()
        if item.get("error") or status == "error" or decision == "error":
            errors += 1
        if item.get("gate_blocked") is True or decision in {"block", "blocked", "deny", "denied"}:
            blocked += 1

        lat = _extract_latency_ms(item)
        if lat is not None:
            latencies.append(lat)

    latencies.sort()
    return {
        "db_path": str(path),
        "total_spans": total,
        "pending_spans": pending,
        "flushed_spans": flushed,
        "error_count": errors,
        "error_rate": round(errors / total, 6) if total > 0 else 0.0,
        "blocked_count": blocked,
        "block_rate": round(blocked / total, 6) if total > 0 else 0.0,
        "latency_samples": len(latencies),
        "p50_latency_ms": _percentile(latencies, 50.0),
        "p95_latency_ms": _percentile(latencies, 95.0),
    }


def _format_human(stats: dict[str, Any]) -> str:
    p50 = f"{stats['p50_latency_ms']:.2f} ms" if stats["p50_latency_ms"] is not None else "n/a"
    p95 = f"{stats['p95_latency_ms']:.2f} ms" if stats["p95_latency_ms"] is not None else "n/a"
    lines = [
        f"MCP Observatory SQLite Stats ({stats['db_path']})",
        f"  total_spans   : {stats['total_spans']}",
        f"  pending_spans : {stats['pending_spans']}",
        f"  flushed_spans : {stats['flushed_spans']}",
        f"  error_rate    : {stats['error_rate'] * 100:.2f}% ({stats['error_count']}/{stats['total_spans']})",
        f"  block_rate    : {stats['block_rate'] * 100:.2f}% ({stats['blocked_count']}/{stats['total_spans']})",
        f"  p50_latency   : {p50}",
        f"  p95_latency   : {p95}",
    ]
    return "\n".join(lines)


def _format_rollup_human(rollup: dict[str, Any]) -> str:
    p50 = (
        f"{rollup['p50_latency_ms']:.2f} ms"
        if rollup["p50_latency_ms"] is not None
        else "n/a"
    )
    p95 = (
        f"{rollup['p95_latency_ms']:.2f} ms"
        if rollup["p95_latency_ms"] is not None
        else "n/a"
    )
    lines = [
        f"MCP Observatory Telemetry Rollup ({rollup['db_path']})",
        f"  total_events : {rollup['total_events']}",
        f"  error_rate   : {rollup['error_rate'] * 100:.2f}% ({rollup['error_count']}/{rollup['total_events']})",
        f"  tokens_in    : {rollup['tokens_in']}",
        f"  tokens_out   : {rollup['tokens_out']}",
        f"  cost_usd     : ${rollup['cost_usd']:.6f}",
        f"  p50_latency  : {p50}",
        f"  p95_latency  : {p95}",
    ]
    by_repo = rollup.get("by_source_repo") or {}
    if by_repo:
        lines.append("  by_source_repo:")
        for repo, stats in by_repo.items():
            repo_p95 = (
                f"{stats['p95_latency_ms']:.2f} ms"
                if stats["p95_latency_ms"] is not None
                else "n/a"
            )
            lines.append(
                f"    - {repo}: events={stats['total_events']} "
                f"errors={stats['error_count']} cost=${stats['cost_usd']:.6f} p95={repo_p95}"
            )
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mcp-observatory",
        description="Local inspector CLI for MCP Observatory.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    stats_cmd = sub.add_parser("stats", help="Inspect span counts, rates, and latency percentiles")
    stats_cmd.add_argument("--db", required=True, help="Path to SQLiteSpanExporter database file")
    stats_cmd.add_argument(
        "--json",
        dest="as_json",
        action="store_true",
        help="Emit machine-readable JSON output",
    )

    export_cmd = sub.add_parser(
        "export",
        help="Export filtered spans to a tamper-evident audit-bundle-v1 file",
    )
    export_cmd.add_argument("--db", required=True, help="Path to SQLiteSpanExporter database file")
    export_cmd.add_argument("--out", required=True, help="Output bundle file path")
    export_cmd.add_argument(
        "--format",
        dest="fmt",
        default="jsonl",
        choices=("jsonl", "csv"),
        help="Export file format (jsonl or csv)",
    )
    export_cmd.add_argument("--tool", dest="tool_name", default=None, help="Filter by tool name")
    export_cmd.add_argument("--status", default=None, help="Filter by span status")
    export_cmd.add_argument(
        "--min-risk",
        dest="min_risk",
        type=float,
        default=None,
        help="Filter by minimum risk score",
    )
    export_cmd.add_argument("--since", dest="since_iso", default=None, help="ISO-8601 start time")
    export_cmd.add_argument("--until", dest="until_iso", default=None, help="ISO-8601 end time")
    export_cmd.add_argument("--limit", type=int, default=500, help="Maximum spans to export")
    export_cmd.add_argument(
        "--json",
        dest="as_json",
        action="store_true",
        help="Emit machine-readable JSON manifest",
    )

    verify_cmd = sub.add_parser(
        "verify-bundle",
        help="Verify SHA-256 hash chain integrity of an exported audit bundle",
    )
    verify_cmd.add_argument("bundle_path", help="Path to exported audit bundle (.jsonl or .csv)")
    verify_cmd.add_argument(
        "--json",
        dest="as_json",
        action="store_true",
        help="Emit machine-readable JSON verification result",
    )

    ingest_cmd = sub.add_parser(
        "ingest-telemetry",
        help="Ingest a weave-telemetry-v1 JSONL stream into SQLite WAL storage",
    )
    ingest_cmd.add_argument("--db", required=True, help="Path to telemetry SQLite database file")
    ingest_cmd.add_argument(
        "--input",
        dest="input_path",
        required=True,
        help="Path to weave-telemetry-v1 JSONL file",
    )
    ingest_cmd.add_argument(
        "--json",
        dest="as_json",
        action="store_true",
        help="Emit machine-readable JSON ingestion summary",
    )

    rollup_cmd = sub.add_parser(
        "rollup",
        help="Compute latency percentile, error rate, and cost rollups from telemetry events",
    )
    rollup_cmd.add_argument("--db", required=True, help="Path to telemetry SQLite database file")
    rollup_cmd.add_argument(
        "--repo",
        dest="source_repo",
        default=None,
        help="Filter rollup by source_repo",
    )
    rollup_cmd.add_argument(
        "--since",
        dest="since_iso",
        default=None,
        help="Filter events at or after ISO-8601 timestamp",
    )
    rollup_cmd.add_argument(
        "--json",
        dest="as_json",
        action="store_true",
        help="Emit machine-readable JSON rollup",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    from mcp_observatory.exporters.query import AuditQueryEngine, verify_audit_bundle

    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "stats":
        try:
            stats = compute_sqlite_stats(args.db)
        except FileNotFoundError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        if args.as_json:
            print(json.dumps(stats, indent=2))
        else:
            print(_format_human(stats))
        return 0

    if args.command == "export":
        try:
            engine = AuditQueryEngine(args.db)
            manifest = engine.export_audit_bundle(
                args.out,
                fmt=args.fmt,
                tool_name=args.tool_name,
                status=args.status,
                min_risk=args.min_risk,
                since_iso=args.since_iso,
                until_iso=args.until_iso,
                limit=args.limit,
            )
        except (FileNotFoundError, ValueError) as exc:
            print(str(exc), file=sys.stderr)
            return 1
        if args.as_json:
            print(json.dumps(manifest, indent=2))
        else:
            print(
                f"Exported {manifest['record_count']} spans ({manifest['format']}) "
                f"to {args.out} [head={manifest['chain_head_sha256'][:12]}...]"
            )
        return 0

    if args.command == "verify-bundle":
        ok, errors = verify_audit_bundle(args.bundle_path)
        if args.as_json:
            print(
                json.dumps(
                    {
                        "valid": ok,
                        "bundle_path": str(args.bundle_path),
                        "errors": errors,
                    },
                    indent=2,
                )
            )
        elif ok:
            print(f"VALID: {args.bundle_path}")
        else:
            print(f"INVALID: {args.bundle_path}", file=sys.stderr)
            for err in errors:
                print(f"  - {err}", file=sys.stderr)
        return 0 if ok else 1

    if args.command == "ingest-telemetry":
        from mcp_observatory.exporters.telemetry import TelemetryRollupEngine

        try:
            with TelemetryRollupEngine(args.db) as engine:
                summary = engine.ingest_jsonl(args.input_path)
        except FileNotFoundError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        if args.as_json:
            print(json.dumps(summary, indent=2))
        else:
            print(
                f"Ingested {summary['ingested']} events "
                f"(skipped_duplicates={summary['skipped_duplicates']}, invalid={summary['invalid']})"
            )
        return 0

    if args.command == "rollup":
        from mcp_observatory.exporters.telemetry import TelemetryRollupEngine

        db_path = Path(args.db)
        if str(args.db) != ":memory:" and not db_path.is_file():
            print(f"Telemetry SQLite database not found: {db_path}", file=sys.stderr)
            return 1
        try:
            with TelemetryRollupEngine(args.db) as engine:
                rollup = engine.compute_rollup(
                    source_repo=args.source_repo,
                    since_iso=args.since_iso,
                )
        except (FileNotFoundError, ValueError) as exc:
            print(str(exc), file=sys.stderr)
            return 1
        if args.as_json:
            print(json.dumps(rollup, indent=2))
        else:
            print(_format_rollup_human(rollup))
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
