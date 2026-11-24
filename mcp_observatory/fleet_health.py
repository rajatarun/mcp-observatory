"""Multi-node fleet health and SLO rollup aggregator producing ``fleet-health-v1``."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

FLEET_HEALTH_SCHEMA = "fleet-health-v1"
VALID_BUDGET_MODES = frozenset({"normal", "prefer_local", "local_only", "halt"})
DEGRADED_BUDGET_MODES = frozenset({"local_only", "halt"})


def _parse_rfc3339(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str) and value.strip():
        normalized = value.strip()
        if normalized.endswith("Z"):
            normalized = normalized[:-1] + "+00:00"
        dt = datetime.fromisoformat(normalized)
    else:
        raise ValueError(f"invalid RFC 3339 timestamp: {value!r}")

    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _format_rfc3339(dt: datetime) -> str:
    utc_dt = dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)
    return utc_dt.isoformat().replace("+00:00", "Z")


def _evaluate_slo_passed(slo_report: dict[str, Any] | None) -> tuple[bool, list[str]]:
    if slo_report is None:
        return True, []
    if not isinstance(slo_report, dict):
        return False, ["invalid slo_report payload"]

    if isinstance(slo_report.get("passed"), bool):
        passed = slo_report["passed"]
        return (True, []) if passed else (False, ["slo_report reported passed=false"])

    status = str(slo_report.get("status") or "pass").lower()
    if status in {"breach", "fail", "failed", "error"}:
        reasons: list[str] = []
        breaches = slo_report.get("breaches")
        if isinstance(breaches, list):
            for item in breaches:
                if isinstance(item, dict) and item.get("severity", "breach") == "breach":
                    msg = item.get("message") or item.get("metric")
                    if msg:
                        reasons.append(f"slo breach: {msg}")
        if not reasons:
            reasons.append(f"slo status={status}")
        return False, reasons

    return True, []


@dataclass
class FleetNodeInput:
    """Per-node health, SLO, and budget input for fleet aggregation."""

    node_id: str
    last_seen_at: str | datetime
    slo_report: dict[str, Any] | None = None
    budget_mode: str = "normal"
    active_wapps: int = 0
    device_unhealthy_count: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.node_id, str) or not self.node_id.strip():
            raise ValueError("node_id must be a non-empty string")
        if self.budget_mode not in VALID_BUDGET_MODES:
            raise ValueError(
                f"budget_mode must be one of {sorted(VALID_BUDGET_MODES)}, got {self.budget_mode!r}"
            )
        if isinstance(self.active_wapps, bool) or not isinstance(self.active_wapps, int) or self.active_wapps < 0:
            raise ValueError("active_wapps must be a non-negative integer")
        if (
            isinstance(self.device_unhealthy_count, bool)
            or not isinstance(self.device_unhealthy_count, int)
            or self.device_unhealthy_count < 0
        ):
            raise ValueError("device_unhealthy_count must be a non-negative integer")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FleetNodeInput:
        if not isinstance(data, dict):
            raise TypeError("fleet node entry must be a JSON object")
        return cls(
            node_id=str(data["node_id"]),
            last_seen_at=data["last_seen_at"],
            slo_report=data.get("slo_report"),
            budget_mode=str(data.get("budget_mode", "normal")),
            active_wapps=int(data.get("active_wapps", 0)),
            device_unhealthy_count=int(data.get("device_unhealthy_count", 0)),
        )


class FleetHealthAggregator:
    """Aggregates per-node signals into a canonical ``fleet-health-v1`` report."""

    def __init__(self, fleet_id: str, stale_after_seconds: int = 300) -> None:
        if not isinstance(fleet_id, str) or not fleet_id.strip():
            raise ValueError("fleet_id must be a non-empty string")
        if (
            isinstance(stale_after_seconds, bool)
            or not isinstance(stale_after_seconds, (int, float))
            or stale_after_seconds < 0
        ):
            raise ValueError("stale_after_seconds must be non-negative")
        self.fleet_id = fleet_id
        self.stale_after_seconds = int(stale_after_seconds)

    def aggregate(
        self,
        nodes: list[FleetNodeInput],
        *,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Compute a canonical ``fleet-health-v1`` payload for ``nodes``."""
        now_dt = _parse_rfc3339(now) if now is not None else datetime.now(UTC)

        node_entries: list[dict[str, Any]] = []
        healthy_count = 0
        degraded_count = 0
        offline_count = 0

        for node in nodes:
            last_seen_dt = _parse_rfc3339(node.last_seen_at)
            age_seconds = (now_dt - last_seen_dt).total_seconds()
            slo_passed, slo_reasons = _evaluate_slo_passed(node.slo_report)

            reasons: list[str] = []
            if age_seconds > self.stale_after_seconds:
                status = "offline"
                offline_count += 1
                reasons.append(
                    f"heartbeat stale ({int(age_seconds)}s > {self.stale_after_seconds}s)"
                )
            else:
                if not slo_passed:
                    reasons.extend(slo_reasons)
                if node.budget_mode in DEGRADED_BUDGET_MODES:
                    reasons.append(f"budget_mode={node.budget_mode}")
                if node.device_unhealthy_count > 0:
                    reasons.append(f"unhealthy_devices={node.device_unhealthy_count}")

                if reasons:
                    status = "degraded"
                    degraded_count += 1
                else:
                    status = "healthy"
                    healthy_count += 1

            node_entries.append(
                {
                    "node_id": node.node_id,
                    "status": status,
                    "slo_passed": slo_passed,
                    "budget_mode": node.budget_mode,
                    "active_wapps": node.active_wapps,
                    "last_seen_at": _format_rfc3339(last_seen_dt),
                    "reasons": reasons,
                }
            )

        total_nodes = len(node_entries)
        non_healthy = degraded_count + offline_count
        if total_nodes == 0:
            overall_status = "healthy"
        elif offline_count > 0 or (non_healthy * 2) > total_nodes:
            overall_status = "critical"
        elif degraded_count > 0:
            overall_status = "degraded"
        else:
            overall_status = "healthy"

        return {
            "schema": FLEET_HEALTH_SCHEMA,
            "fleet_id": self.fleet_id,
            "generated_at": _format_rfc3339(now_dt),
            "nodes": node_entries,
            "summary": {
                "total_nodes": total_nodes,
                "healthy": healthy_count,
                "degraded": degraded_count,
                "offline": offline_count,
                "overall_status": overall_status,
            },
        }


def load_fleet_node_inputs(input_path: str | Path) -> list[FleetNodeInput]:
    """Load ``FleetNodeInput`` entries from a ``.json`` or ``.jsonl`` file."""
    path = Path(input_path)
    if not path.is_file():
        raise FileNotFoundError(f"Fleet input file not found: {path}")

    raw_text = path.read_text(encoding="utf-8").strip()
    if not raw_text:
        return []

    if path.suffix.lower() == ".jsonl":
        entries = [json.loads(line) for line in raw_text.splitlines() if line.strip()]
    else:
        parsed = json.loads(raw_text)
        if isinstance(parsed, list):
            entries = parsed
        elif isinstance(parsed, dict) and isinstance(parsed.get("nodes"), list):
            entries = parsed["nodes"]
        else:
            raise ValueError("JSON fleet input must be a list of nodes or an object with a 'nodes' array")

    return [FleetNodeInput.from_dict(item) for item in entries]


__all__ = [
    "DEGRADED_BUDGET_MODES",
    "FLEET_HEALTH_SCHEMA",
    "VALID_BUDGET_MODES",
    "FleetHealthAggregator",
    "FleetNodeInput",
    "load_fleet_node_inputs",
]
