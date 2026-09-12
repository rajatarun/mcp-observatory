#!/usr/bin/env python3
"""
Worst-case cost of the propose/commit gate against adversarially sized inputs.

The paper reports a 0.0996 ms median for the full gate path on ~100-byte
inputs. That is the typical case. The question a deployer actually has is
how the cost grows when an agent (or an attacker) hands the gate a 1 MB
argument mapping or a 100 KB answer, because the gate sits on the request
path and everything linear in input size becomes a latency budget.

docs/gate-properties.md P5 claims every step is linear in its input, with
key sorting the only super-linear term. This script measures each step and
the full path at input sizes spanning four orders of magnitude and prints
the observed scaling exponent, so the claim is checked rather than stated.

Usage
-----
  python scripts/bench_gate.py                 # default sizes, 200 iterations per point
  python scripts/bench_gate.py --iters 50 --max-kb 4096
  python scripts/bench_gate.py --json out.json
"""
from __future__ import annotations

import argparse
import json
import math
import random
import statistics
import string
import sys
import time
from typing import Callable

from mcp_observatory.proposal_commit.hashing import tool_args_hash
from mcp_observatory.proposal_commit.scoring import composite_score, numeric_variance, output_instability
from mcp_observatory.proposal_commit.token import CommitTokenManager
from mcp_observatory.risk.signals import grounding_risk, self_consistency_risk
from mcp_observatory.risk.vector import compute_risk_vector

SIZES_KB = [0.1, 1, 10, 100, 1000]


def _rand_words(rng: random.Random, n_bytes: int) -> str:
    words = []
    total = 0
    while total < n_bytes:
        w = "".join(rng.choices(string.ascii_lowercase, k=rng.randint(3, 9)))
        if rng.random() < 0.2:
            w = str(rng.randint(0, 99999))
        words.append(w)
        total += len(w) + 1
    return " ".join(words)


def _args_of_size(rng: random.Random, n_bytes: int) -> dict:
    """Wide, shallow mapping with many keys: the worst case for sort_keys."""
    args: dict = {}
    total = 0
    i = 0
    while total < n_bytes:
        k = f"k{i:06d}"
        v = _rand_words(rng, 40)
        args[k] = v
        total += len(k) + len(v) + 6
        i += 1
    return args


def _time(fn: Callable[[], object], iters: int) -> tuple[float, float]:
    """Return (median_ms, p99_ms)."""
    samples = []
    for _ in range(iters):
        t0 = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - t0) * 1000.0)
    samples.sort()
    return statistics.median(samples), samples[min(len(samples) - 1, int(0.99 * len(samples)))]


def _slope(xs: list[float], ys: list[float]) -> float:
    """Least-squares slope of log(y) on log(x): the empirical scaling exponent."""
    lx = [math.log(x) for x in xs]
    ly = [math.log(max(y, 1e-9)) for y in ys]
    mx, my = statistics.mean(lx), statistics.mean(ly)
    num = sum((a - mx) * (b - my) for a, b in zip(lx, ly))
    den = sum((a - mx) ** 2 for a in lx)
    return num / den if den else float("nan")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--iters", type=int, default=200)
    ap.add_argument("--max-kb", type=float, default=1000)
    ap.add_argument("--json", default=None)
    args = ap.parse_args()

    rng = random.Random(0)
    sizes = [s for s in SIZES_KB if s <= args.max_kb]
    tm = CommitTokenManager(secret="bench", ttl_seconds=60)
    results: dict[str, dict] = {}

    print(f"iters/point={args.iters}   sizes (KB)={sizes}")
    print(f"{'step':<34}" + "".join(f"{s:>10g}KB" for s in sizes) + "   exponent")

    def report(name: str, fn_for_size: Callable[[int], Callable[[], object]], iters_scale: bool = True):
        meds, p99s = [], []
        for s in sizes:
            n = int(s * 1024)
            fn = fn_for_size(n)
            iters = max(5, int(args.iters / (1 + s / 50))) if iters_scale else args.iters
            med, p99 = _time(fn, iters)
            meds.append(med)
            p99s.append(p99)
        exp = _slope([s * 1024 for s in sizes], meds)
        results[name] = {"sizes_kb": sizes, "median_ms": meds, "p99_ms": p99s, "exponent": exp}
        print(f"{name:<34}" + "".join(f"{m:12.3f}" for m in meds) + f"   {exp:6.2f}")

    # ── argument path ────────────────────────────────────────────────────────
    report("args hash (canonical JSON+SHA256)",
           lambda n: (lambda a=_args_of_size(rng, n): (lambda: tool_args_hash(a)))())

    # Token payload is fixed-size except for tool_name; scale tool_name to be
    # adversarial. Issue+verify.
    def token_fn(n):
        name = "t" * n
        def go():
            t = tm.issue(proposal_id="p", tool_name=name, tool_args_hash="h", composite_score=0.1)
            tm.verify(t.token)
        return go
    report("token issue+verify (tool_name=N)", token_fn)

    # ── text signals ─────────────────────────────────────────────────────────
    def two_texts(n):
        a = _rand_words(rng, n)
        b = _rand_words(rng, n)
        return a, b

    report("output instability (Jaccard)",
           lambda n: (lambda ab=two_texts(n): (lambda: output_instability(*ab)))())
    report("numeric variance",
           lambda n: (lambda ab=two_texts(n): (lambda: numeric_variance(*ab)))())
    report("grounding risk (Jaccard)",
           lambda n: (lambda ab=two_texts(n): (lambda: grounding_risk(*ab)))())
    report("self-consistency risk (Jaccard)",
           lambda n: (lambda ab=two_texts(n): (lambda: self_consistency_risk(*ab)))())

    # ── full paths ───────────────────────────────────────────────────────────
    def full_pc(n):
        a = _args_of_size(rng, n)
        oa, ob = two_texts(n)
        def go():
            h = tool_args_hash(a)
            s = composite_score({"output_instability": output_instability(oa, ob),
                                 "numeric_variance": numeric_variance(oa, ob),
                                 "prompt_drift": None})
            t = tm.issue(proposal_id="p", tool_name="tool", tool_args_hash=h, composite_score=s or 0.0)
            tm.verify(t.token)
        return go
    report("FULL propose/commit path (args+text=N)", full_pc)

    def full_v2(n):
        a, b = two_texts(n)
        ctx = _rand_words(rng, n)
        def go():
            compute_risk_vector(prompt="p", answer=a, retrieved_context=ctx, secondary_answer=b,
                                tool_result_summary="ok done", previous_prompt_hash="x")
        return go
    report("FULL six-signal risk vector (text=N)", full_v2)

    print("\nexponent ~1.0 = linear in input size; ~0 = independent of it. p99 in the JSON.")
    print("A 1 MB argument mapping costs what the first row says; the guard for that is an "
          "input-size limit upstream, not anything in the gate.")
    if args.json:
        with open(args.json, "w") as f:
            json.dump(results, f, indent=2)
        print(f"wrote {args.json}")


if __name__ == "__main__":
    sys.exit(main())
