"""Properties of the propose/commit gate, checked rather than asserted.

Each test here corresponds to a numbered property in docs/gate-properties.md.
The mutation tests are exhaustive over the fields they cover: every payload
field, every argument edit, every binding the verifier is supposed to enforce.
A property that holds for the cases someone happened to think of is not a
property; the point of enumerating is that a new field or a reordered check
cannot slip past without a test changing.
"""
from __future__ import annotations

import asyncio
import base64
import json
import random

import pytest

from mcp_observatory.demo.server import DemoToolServer
from mcp_observatory.policy.engine import PolicyConfig, PolicyEngine
from mcp_observatory.policy.types import Criticality, Decision, ToolProfile
from mcp_observatory.proposal_commit import scoring as pc_scoring
from mcp_observatory.proposal_commit import token as pc_token
from mcp_observatory.proposal_commit.hashing import tool_args_hash
from mcp_observatory.proposal_commit.proposer import ToolProposer
from mcp_observatory.proposal_commit.storage import InMemoryStorage
from mcp_observatory.proposal_commit.token import CommitTokenManager
from mcp_observatory.proposal_commit.verifier import CommitVerifier
from mcp_observatory.risk import scoring as risk_scoring
from mcp_observatory.risk import signals as risk_signals
from mcp_observatory.risk.vector import compute_risk_vector
from mcp_observatory.token import verifier as v2_verifier_module
from mcp_observatory.token.issuer import TokenIssuer
from mcp_observatory.token.verifier import TokenVerifier


def run(coro):
    return asyncio.run(coro)


# ─────────────────────────────────────────────────────────────────────────────
# P1  Monotonicity and bounded influence of the composite
# ─────────────────────────────────────────────────────────────────────────────

def _random_instance(rng: random.Random, keys):
    weights = {k: rng.uniform(0.01, 1.0) for k in keys}
    defined = [k for k in keys if rng.random() < 0.7] or [rng.choice(keys)]
    signals = {k: (rng.uniform(0.0, 1.0) if k in defined else None) for k in keys}
    return weights, signals, defined


@pytest.mark.parametrize("composite,keys", [
    (lambda s, w: risk_scoring.composite_risk_score(s, w)[0], list(risk_scoring.DEFAULT_WEIGHTS)),
    (pc_scoring.composite_score, list(pc_scoring.DEFAULT_WEIGHTS)),
])
def test_p1_composite_is_monotone_and_lipschitz_in_each_defined_signal(composite, keys):
    """For fixed D: raising r_i never lowers s, and moves it by <= w_i / W_D * delta."""
    rng = random.Random(1234)
    for _ in range(3000):
        weights, signals, defined = _random_instance(rng, keys)
        i = rng.choice(defined)
        s0 = composite(signals, weights)
        bumped = dict(signals)
        delta = rng.uniform(0.0, 1.0 - signals[i])
        bumped[i] = signals[i] + delta
        s1 = composite(bumped, weights)
        assert s1 >= s0 - 1e-12, (signals, bumped, weights)
        w_d = sum(weights[k] for k in defined)
        assert s1 - s0 <= weights[i] / w_d * delta + 1e-9


def test_p1_defined_set_change_is_not_comparable_and_count_is_exposed():
    """Adding a signal can move s either way; |D| is what makes two scores comparable."""
    s_one, _ = risk_scoring.composite_risk_score({"verifier_risk": 0.5})
    s_two_down, _ = risk_scoring.composite_risk_score({"verifier_risk": 0.5, "grounding_risk": 0.0})
    s_two_up, _ = risk_scoring.composite_risk_score({"verifier_risk": 0.5, "grounding_risk": 1.0})
    assert s_two_down < s_one < s_two_up
    assert risk_scoring.defined_signal_count({"verifier_risk": 0.5}) == 1
    assert risk_scoring.defined_signal_count({"verifier_risk": 0.5, "grounding_risk": 0.0}) == 2


# ─────────────────────────────────────────────────────────────────────────────
# P2  No score from no evidence; absent input is undefined, not zero
# ─────────────────────────────────────────────────────────────────────────────

def test_p2_empty_signal_set_yields_no_score():
    assert risk_scoring.composite_risk_score({}) == (None, "unknown")
    assert risk_scoring.composite_risk_score({k: None for k in risk_scoring.DEFAULT_WEIGHTS}) == (None, "unknown")
    assert pc_scoring.composite_score({}) is None


def test_p2_signals_with_no_input_are_undefined_not_zero():
    """0.0 said 'no drift' / 'no mismatch'; the truth was 'not observed'."""
    assert risk_signals.drift_risk(previous_prompt_hash=None, current_prompt_hash="h") is None
    assert risk_signals.drift_risk(previous_prompt_hash="h", current_prompt_hash="h") == 0.0
    assert risk_signals.tool_mismatch_risk("done", None) is None
    assert risk_signals.tool_mismatch_risk("done", "ok") == 0.0


@pytest.mark.parametrize("crit,expected", [
    (Criticality.HIGH, Decision.REVIEW),
    (Criticality.MEDIUM, Decision.REVIEW),
    (Criticality.LOW, Decision.ALLOW),
])
def test_p2_policy_never_allows_a_critical_tool_on_no_score(crit, expected):
    engine = PolicyEngine()
    res = engine.evaluate(tool_profile=ToolProfile("t", criticality=crit), composite_risk_score=None)
    assert res.decision == expected
    if expected == Decision.REVIEW:
        assert res.reason.endswith("no_risk_signals")


def test_p2_bare_confident_answer_no_longer_clears_a_high_criticality_tool():
    """The reachable fail-open.

    With no retrieval, no resample, no tool result and no prior prompt, the
    six-signal vector used to be {verifier ~0, tool_mismatch 0.0, drift 0.0}:
    three 'signals' of which two were placeholders for missing input, composite
    ~0, level low, and a HIGH-criticality tool was ALLOWED. Renormalisation did
    not save it because the zeros were in D. Now only the verifier signal is
    defined, |D| = 1, and the policy routes to review for lack of evidence.
    """
    rv = compute_risk_vector(prompt="transfer now", answer="transfer completed successfully")
    assert rv.tool_mismatch_risk is None and rv.drift_risk is None
    assert rv.signals_defined == 1
    res = PolicyEngine().evaluate(
        tool_profile=ToolProfile("execute_transfer", criticality=Criticality.HIGH),
        composite_risk_score=rv.composite_risk_score,
        signals_defined=rv.signals_defined,
    )
    assert res.decision == Decision.REVIEW
    assert res.reason == "high_criticality_insufficient_evidence"


def test_p2_enough_evidence_restores_the_score_based_decision():
    rv = compute_risk_vector(
        prompt="transfer now",
        answer="transfer completed",
        retrieved_context="transfer completed for account",
        secondary_answer="transfer completed",
    )
    assert rv.signals_defined >= PolicyConfig().min_signals_high
    res = PolicyEngine().evaluate(
        tool_profile=ToolProfile("execute_transfer", criticality=Criticality.HIGH),
        composite_risk_score=rv.composite_risk_score,
        signals_defined=rv.signals_defined,
    )
    assert res.reason.startswith("high_criticality_") and "evidence" not in res.reason


def test_p2_proposer_blocks_when_no_signal_is_defined(monkeypatch):
    """Reachable only by direct API misuse today (instability is always defined), so enforced anyway."""
    monkeypatch.setattr("mcp_observatory.proposal_commit.proposer.composite_score", lambda signals: None)
    storage = InMemoryStorage()
    proposer = ToolProposer(storage=storage, token_manager=CommitTokenManager(secret="s"))
    res = run(proposer.propose(tool_name="t", tool_args={"a": 1}, prompt="p",
                               candidate_output_a="x", candidate_output_b="x"))
    assert res["status"] == "blocked" and res["reason"] == "no_signals"
    assert "commit_token" not in res
    assert list(storage.proposals.values())[0]["decision"] == "block"


# ─────────────────────────────────────────────────────────────────────────────
# P3  Token integrity: every payload field is under the signature
# ─────────────────────────────────────────────────────────────────────────────

def _split(token: str):
    payload_b64, sig_b64 = token.split(".", 1)
    return json.loads(base64.urlsafe_b64decode(payload_b64)), sig_b64


def _reassemble(payload: dict, sig_b64: str) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return f"{base64.urlsafe_b64encode(raw).decode()}.{sig_b64}"


def _mutate(value):
    if isinstance(value, bool):
        return not value
    if isinstance(value, int):
        return value + 1
    if isinstance(value, float):
        return value + 0.1
    if isinstance(value, str):
        return value + "x"
    return "mutated"


def test_p3_commit_token_every_field_is_bound_by_the_signature():
    tm = CommitTokenManager(secret="unit-secret", ttl_seconds=60)
    issued = tm.issue(proposal_id="p1", tool_name="transfer_funds", tool_args_hash="h", composite_score=0.2)
    assert tm.verify(issued.token).valid
    payload, sig = _split(issued.token)
    assert set(payload) == {"token_id", "proposal_id", "tool_name", "tool_args_hash",
                            "issued_at", "expires_at", "nonce", "composite_score"}
    for field in payload:
        tampered = dict(payload)
        tampered[field] = _mutate(payload[field])
        assert tm.verify(_reassemble(tampered, sig)).reason == "bad_signature", field
    # Added field, removed field, flipped signature bit, malformed token, wrong secret.
    assert tm.verify(_reassemble({**payload, "extra": 1}, sig)).reason == "bad_signature"
    dropped = {k: v for k, v in payload.items() if k != "nonce"}
    assert tm.verify(_reassemble(dropped, sig)).reason == "bad_signature"
    raw_sig = bytearray(base64.urlsafe_b64decode(sig))
    raw_sig[0] ^= 0x01
    assert tm.verify(_reassemble(payload, base64.urlsafe_b64encode(bytes(raw_sig)).decode())).reason == "bad_signature"
    assert tm.verify("not-a-token").reason == "bad_signature"
    assert CommitTokenManager(secret="other").verify(issued.token).reason == "bad_signature"
    # The token *string* is canonical: the lenient base64 decoder used to accept
    # trailing bytes after the padding, so token+"x" verified. Found by the
    # side-effect test below, which committed a transfer with a mangled token.
    p64, s64 = issued.token.split(".", 1)
    for spelling in (issued.token + "x", f"{p64}x.{s64}", f"{p64}.{s64}==", f"{p64}.x{s64}"):
        assert tm.verify(spelling).reason == "bad_signature", spelling
    # The secret is the whole trust root: a different instance with the same secret accepts.
    assert CommitTokenManager(secret="unit-secret").verify(issued.token).valid


def test_p3_execution_token_every_field_is_bound_by_the_signature():
    issuer = TokenIssuer(secret_key="k", ttl_ms=60_000)
    issued = issuer.issue(trace_id="t", tool_name="tool", tool_args_hash="h", decision="ALLOW", composite_risk_score=0.1)
    payload, sig = _split(issued.token)
    for field in payload:
        tampered = dict(payload)
        tampered[field] = _mutate(payload[field])
        v = TokenVerifier(secret_key="k").verify(_reassemble(tampered, sig), tool_name="tool", tool_args_hash="h")
        assert v.reason == "invalid_signature", field
    assert TokenVerifier(secret_key="k2").verify(issued.token, tool_name="tool", tool_args_hash="h").reason == "invalid_signature"
    assert TokenVerifier(secret_key="k").verify(issued.token + "x", tool_name="tool", tool_args_hash="h").reason == "token_decode_failed"


def test_p3_commit_token_expiry_is_enforced(monkeypatch):
    tm = CommitTokenManager(secret="s", ttl_seconds=60)
    issued = tm.issue(proposal_id="p", tool_name="t", tool_args_hash="h", composite_score=0.0)
    real = pc_token.time
    monkeypatch.setattr(pc_token, "time", lambda: real() + 61)
    assert tm.verify(issued.token).reason == "expired"


# ─────────────────────────────────────────────────────────────────────────────
# P4  Commit soundness: the call that executes is the call that was scored
# ─────────────────────────────────────────────────────────────────────────────

ARGS = {"amount": 100, "to": "acct_123", "meta": {"x": 1, "y": 2}}


def _allowed_proposal(proposer, tool="place_trade", args=ARGS):
    res = run(proposer.propose(tool_name=tool, tool_args=args, prompt="do it",
                               candidate_output_a="plan 100", candidate_output_b="plan 100"))
    assert res["status"] == "allowed", res
    return res


def _gate():
    storage = InMemoryStorage()
    tm = CommitTokenManager(secret="unit-secret", ttl_seconds=60)
    return storage, tm, ToolProposer(storage=storage, token_manager=tm), CommitVerifier(storage=storage, token_manager=tm)


def _arg_mutations(args: dict):
    """Every single edit to the argument mapping, plus the one that must be accepted."""
    yield "value_changed", {**args, "amount": 101}, False
    yield "value_type_changed", {**args, "amount": "100"}, False
    yield "key_added", {**args, "note": ""}, False
    yield "key_removed", {k: v for k, v in args.items() if k != "to"}, False
    yield "nested_value_changed", {**args, "meta": {"x": 1, "y": 3}}, False
    yield "nested_key_removed", {**args, "meta": {"x": 1}}, False
    yield "keys_reordered", {"to": args["to"], "meta": {"y": 2, "x": 1}, "amount": args["amount"]}, True


def test_p4_every_argument_edit_between_phases_is_rejected_and_reordering_is_not():
    for name, mutated, should_pass in _arg_mutations(ARGS):
        _, _, proposer, verifier = _gate()
        p = _allowed_proposal(proposer)
        v = run(verifier.verify_commit(proposal_id=p["proposal_id"], commit_token=p["commit_token"],
                                       tool_name="place_trade", tool_args=mutated))
        assert v.ok is should_pass, (name, v)
        if not should_pass:
            assert v.reason == "args_hash_mismatch", name
    assert tool_args_hash(ARGS) == tool_args_hash(dict(reversed(list(ARGS.items()))))


def test_p4_tool_name_proposal_binding_and_replay():
    storage, tm, proposer, verifier = _gate()
    a = _allowed_proposal(proposer)
    b = _allowed_proposal(proposer, args={**ARGS, "amount": 5})

    # Tool substitution with the scored arguments.
    v = run(verifier.verify_commit(proposal_id=a["proposal_id"], commit_token=a["commit_token"],
                                   tool_name="cancel_trade", tool_args=ARGS))
    assert not v.ok and v.reason == "args_hash_mismatch"

    # Token of one allowed proposal presented against another allowed proposal.
    v = run(verifier.verify_commit(proposal_id=b["proposal_id"], commit_token=a["commit_token"],
                                   tool_name="place_trade", tool_args=ARGS))
    assert not v.ok and v.reason == "unknown_proposal"

    # Unknown proposal id with a genuine token.
    v = run(verifier.verify_commit(proposal_id="nope", commit_token=a["commit_token"],
                                   tool_name="place_trade", tool_args=ARGS))
    assert not v.ok and v.reason == "unknown_proposal"

    # Legitimate commit, then replay of the identical request.
    first = run(verifier.verify_commit(proposal_id=a["proposal_id"], commit_token=a["commit_token"],
                                       tool_name="place_trade", tool_args=ARGS))
    second = run(verifier.verify_commit(proposal_id=a["proposal_id"], commit_token=a["commit_token"],
                                        tool_name="place_trade", tool_args=ARGS))
    assert first.ok and first.reason == "ok"
    assert not second.ok and second.reason == "nonce_replay"


def test_p4_a_structurally_valid_token_cannot_commit_a_blocked_proposal():
    """Even the issuer's own signature does not override the recorded decision."""
    storage, tm, proposer, verifier = _gate()
    blocked = run(proposer.propose(tool_name="t", tool_args=ARGS, prompt="p",
                                   candidate_output_a="alpha beta gamma 1",
                                   candidate_output_b="delta epsilon 999"))
    assert blocked["status"] == "blocked"
    forged = tm.issue(proposal_id=blocked["proposal_id"], tool_name="t",
                      tool_args_hash=tool_args_hash(ARGS), composite_score=0.0)
    assert tm.verify(forged.token).valid, "forgery premise: the token itself is well-formed"
    v = run(verifier.verify_commit(proposal_id=blocked["proposal_id"], commit_token=forged.token,
                                   tool_name="t", tool_args=ARGS))
    assert not v.ok and v.reason == "unknown_proposal"


def test_p4_no_side_effect_without_a_passing_verification():
    """Fail-closed at the point that matters: the ledger."""
    async def scenario():
        server = DemoToolServer()
        try:
            p = await server.transfer_funds_propose(amount=100, to="acct_123")
            assert p["status"] == "allowed"
            attempts = [
                dict(proposal_id=p["proposal_id"], commit_token=p["commit_token"], amount=101, to="acct_123"),
                dict(proposal_id=p["proposal_id"], commit_token=p["commit_token"], amount=100, to="acct_124"),
                dict(proposal_id="other", commit_token=p["commit_token"], amount=100, to="acct_123"),
                dict(proposal_id=p["proposal_id"], commit_token=p["commit_token"] + "x", amount=100, to="acct_123"),
            ]
            for a in attempts:
                r = await server.transfer_funds_commit(**a)
                assert r["status"] == "blocked", a
                assert server.ledger.transfers == []
            ok = await server.transfer_funds_commit(proposal_id=p["proposal_id"], commit_token=p["commit_token"],
                                                    amount=100, to="acct_123")
            assert ok["status"] == "committed" and len(server.ledger.transfers) == 1
            replay = await server.transfer_funds_commit(proposal_id=p["proposal_id"], commit_token=p["commit_token"],
                                                        amount=100, to="acct_123")
            assert replay["status"] == "blocked" and replay["reason"] == "nonce_replay"
            assert len(server.ledger.transfers) == 1
        finally:
            await server.close()
    run(scenario())


def test_p4_execution_token_binds_tool_and_args_and_detects_replay(monkeypatch):
    issuer = TokenIssuer(secret_key="k", ttl_ms=60_000)
    verifier = TokenVerifier(secret_key="k")
    t = issuer.issue(trace_id="tr", tool_name="tool", tool_args_hash="h", decision="ALLOW", composite_risk_score=0.1).token
    assert verifier.verify(t, tool_name="other", tool_args_hash="h").reason == "tool_name_mismatch"
    assert verifier.verify(t, tool_name="tool", tool_args_hash="h2").reason == "tool_args_hash_mismatch"
    assert verifier.verify(t, tool_name="tool", tool_args_hash="h").valid
    assert verifier.verify(t, tool_name="tool", tool_args_hash="h").reason == "token_replay_detected"
    real = v2_verifier_module.utc_now
    from datetime import timedelta
    monkeypatch.setattr(v2_verifier_module, "utc_now", lambda: real() + timedelta(seconds=61))
    t2 = issuer.issue(trace_id="tr", tool_name="tool", tool_args_hash="h", decision="ALLOW", composite_risk_score=0.1).token
    assert TokenVerifier(secret_key="k").verify(t2, tool_name="tool", tool_args_hash="h").reason == "token_expired"
