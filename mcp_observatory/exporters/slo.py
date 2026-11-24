"""Local SLO evaluator producing canonical ``slo-report-v1`` reports."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from .telemetry import TelemetryRollupEngine

SLO_REPORT_SCHEMA = "slo-report-v1"
WARN_THRESHOLD_RATIO = 0.85


def _validate_non_negative_float(name: str, value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a finite non-negative number")
    result = float(value)
    if not math.isfinite(result) or result < 0.0:
        raise ValueError(f"{name} must be a finite non-negative number")
    return result


@dataclass
class SLOTargets:
    """Service-level objective thresholds for telemetry rollup evaluation."""

    max_p95_latency_ms: float = 2000.0
    max_error_rate: float = 0.05
    max_cost_usd: float = 5.0
    min_events: int = 1

    def __post_init__(self) -> None:
        self.max_p95_latency_ms = _validate_non_negative_float(
            "max_p95_latency_ms", self.max_p95_latency_ms
        )
        self.max_error_rate = _validate_non_negative_float(
            "max_error_rate", self.max_error_rate
        )
        if self.max_error_rate > 1.0:
            raise ValueError("max_error_rate must be between 0.0 and 1.0")
        self.max_cost_usd = _validate_non_negative_float(
            "max_cost_usd", self.max_cost_usd
        )
        if isinstance(self.min_events, bool) or not isinstance(self.min_events, int) or self.min_events < 0:
            raise ValueError("min_events must be a non-negative integer")

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_p95_latency_ms": self.max_p95_latency_ms,
            "max_error_rate": self.max_error_rate,
            "max_cost_usd": self.max_cost_usd,
            "min_events": self.min_events,
        }


class SLOEvaluator:
    """Evaluates SQLite telemetry rollups against SLO targets into ``slo-report-v1``."""

    def __init__(self, engine: TelemetryRollupEngine) -> None:
        self.engine = engine

    def evaluate(
        self,
        *,
        targets: SLOTargets | None = None,
        source_repo: str | None = None,
        since_iso: str | None = None,
        window_label: str = "all",
    ) -> dict[str, Any]:
        """Evaluate telemetry metrics against ``targets`` and return an ``slo-report-v1`` dict."""
        effective_targets = targets if targets is not None else SLOTargets()
        rollup = self.engine.compute_rollup(
            source_repo=source_repo,
            since_iso=since_iso,
        )

        total_events = int(rollup["total_events"])
        error_rate = float(rollup["error_rate"])
        p50_latency_ms = rollup["p50_latency_ms"]
        p95_latency_ms = rollup["p95_latency_ms"]
        total_cost_usd = float(rollup["cost_usd"])

        metrics: dict[str, Any] = {
            "total_events": total_events,
            "error_rate": error_rate,
            "p50_latency_ms": p50_latency_ms,
            "p95_latency_ms": p95_latency_ms,
            "total_cost_usd": total_cost_usd,
        }

        evaluated_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        breaches: list[dict[str, Any]] = []

        if total_events < effective_targets.min_events:
            status = "insufficient_data"
        else:
            checks: list[tuple[str, float | None, float, str]] = [
                (
                    "p95_latency_ms",
                    float(p95_latency_ms) if p95_latency_ms is not None else None,
                    effective_targets.max_p95_latency_ms,
                    "ms",
                ),
                (
                    "error_rate",
                    error_rate,
                    effective_targets.max_error_rate,
                    "",
                ),
                (
                    "total_cost_usd",
                    total_cost_usd,
                    effective_targets.max_cost_usd,
                    "USD",
                ),
            ]

            has_breach = False
            has_warn = False

            for metric_name, observed, threshold, unit in checks:
                if observed is None:
                    continue
                unit_suffix = f" {unit}" if unit else ""
                if observed > threshold:
                    has_breach = True
                    breaches.append(
                        {
                            "metric": metric_name,
                            "observed": observed,
                            "threshold": threshold,
                            "severity": "breach",
                            "message": (
                                f"{metric_name} ({observed}{unit_suffix}) exceeded "
                                f"threshold ({threshold}{unit_suffix})"
                            ),
                        }
                    )
                elif threshold > 0.0 and (
                    observed >= threshold * WARN_THRESHOLD_RATIO
                    or math.isclose(
                        observed,
                        threshold * WARN_THRESHOLD_RATIO,
                        rel_tol=1e-9,
                        abs_tol=1e-12,
                    )
                ):
                    has_warn = True
                    pct = round((observed / threshold) * 100.0, 2)
                    breaches.append(
                        {
                            "metric": metric_name,
                            "observed": observed,
                            "threshold": threshold,
                            "severity": "warn",
                            "message": (
                                f"{metric_name} ({observed}{unit_suffix}) is at "
                                f"{pct}% of threshold ({threshold}{unit_suffix})"
                            ),
                        }
                    )

            if has_breach:
                status = "breach"
            elif has_warn:
                status = "warn"
            else:
                status = "pass"

        return {
            "schema": SLO_REPORT_SCHEMA,
            "evaluated_at": evaluated_at,
            "window_label": window_label,
            "source_repo": source_repo,
            "status": status,
            "metrics": metrics,
            "targets": effective_targets.to_dict(),
            "breaches": breaches,
        }


__all__ = [
    "SLO_REPORT_SCHEMA",
    "WARN_THRESHOLD_RATIO",
    "SLOEvaluator",
    "SLOTargets",
]
