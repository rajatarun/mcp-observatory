"""Channel binding: the token carries the channel strength the call must run over.

The property under test is that an executor cannot downgrade the transport for
a call that was authorised on the assumption of a strong one. The guard that
enforces it sits inside the signed payload, so the tests below check both that
it is enforced and that it cannot be removed.
"""
from __future__ import annotations

import asyncio
import base64
import json

import pytest

from mcp_observatory.proposal_commit import CommitTokenManager, CommitVerifier, ToolProposer
from mcp_observatory.proposal_commit.channel import (
    CHANNEL_BELOW_REQUIRED_PROFILE,
    channel_satisfies,
    normalise_profile,
)
from mcp_observatory.proposal_commit.storage import InMemoryStorage

ARGS = {"amount": 100, "to": "acct_1"}


def run(coro):
    return asyncio.run(coro)


def gate(provider=None, *, require_binding=False):
    storage = InMemoryStorage()
    tm = CommitTokenManager(secret="unit-secret", ttl_seconds=60)
    proposer = ToolProposer(storage=storage, token_manager=tm, channel_profile_provider=provider)
    verifier = CommitVerifier(
        storage=storage, token_manager=tm, require_channel_binding=require_binding
    )
    return proposer, verifier, tm


def allowed(proposer, tool="place_trade", args=ARGS):
    res = run(
        proposer.propose(
            tool_name=tool, tool_args=args, prompt="do it",
            candidate_output_a="plan 100", candidate_output_b="plan 100",
        )
    )
    assert res["status"] == "allowed", res
    return res


# --- the lattice ------------------------------------------------------------

@pytest.mark.parametrize("channel,required,ok", [
    ("QUANTUM_SAFE", "QUANTUM_SAFE", True),
    ("QUANTUM_SAFE", "CHEAP", True),
    ("HARDENED", "BALANCED", True),
    ("BALANCED", "HARDENED", False),
    ("CHEAP", "BALANCED", False),
    ("hardened", "HARDENED", True),          # case-insensitive
    ("  HARDENED  ", "HARDENED", True),      # whitespace-tolerant
])
def test_channel_satisfies_orders_the_lattice(channel, required, ok):
    assert channel_satisfies(channel, required) is ok


@pytest.mark.parametrize("channel", [None, "", "TLS1.3", "unknown", "  "])
def test_an_unplaceable_channel_satisfies_nothing(channel):
    """A channel the verifier cannot place is not evidence of a strong one."""
    assert channel_satisfies(channel, "CHEAP") is False


def test_an_unrecognised_requirement_is_enforced_at_maximum():
    """A corrupted-but-signed profile must refuse, not wave the call through."""
    assert channel_satisfies("HARDENED", "NONSENSE") is False
    assert channel_satisfies("QUANTUM_SAFE", "NONSENSE") is True


def test_normalise_profile_fails_secure():
    assert normalise_profile("hardened") == "HARDENED"
    for bad in [None, "", "nonsense", 7]:
        assert normalise_profile(bad) == "QUANTUM_SAFE"


# --- no provider: nothing changes for the five existing consumers -----------

def test_without_a_provider_no_requirement_is_bound_and_commit_succeeds():
    proposer, verifier, _ = gate()
    p = allowed(proposer)
    payload = json.loads(base64.urlsafe_b64decode(p["commit_token"].split(".", 1)[0]))
    assert "required_cipher_profile" not in payload
    v = run(verifier.verify_commit(
        proposal_id=p["proposal_id"], commit_token=p["commit_token"],
        tool_name="place_trade", tool_args=ARGS,
    ))
    assert v.ok, v


# --- with a provider: the requirement is bound and enforced -----------------

def test_a_weaker_channel_is_refused_and_a_stronger_one_accepted():
    async def provider(tool_name, tool_args):
        return "HARDENED"

    for channel, expect_ok in [("BALANCED", False), ("HARDENED", True), ("QUANTUM_SAFE", True)]:
        proposer, verifier, _ = gate(provider)
        p = allowed(proposer)
        v = run(verifier.verify_commit(
            proposal_id=p["proposal_id"], commit_token=p["commit_token"],
            tool_name="place_trade", tool_args=ARGS, channel_profile=channel,
        ))
        assert v.ok is expect_ok, (channel, v)
        if not expect_ok:
            assert v.reason == CHANNEL_BELOW_REQUIRED_PROFILE


def test_omitting_the_channel_on_a_bound_token_is_refused():
    async def provider(tool_name, tool_args):
        return "BALANCED"

    proposer, verifier, _ = gate(provider)
    p = allowed(proposer)
    v = run(verifier.verify_commit(
        proposal_id=p["proposal_id"], commit_token=p["commit_token"],
        tool_name="place_trade", tool_args=ARGS,
    ))
    assert not v.ok and v.reason == CHANNEL_BELOW_REQUIRED_PROFILE


def test_a_refused_channel_does_not_burn_the_nonce():
    """The guard sits before nonce_seen, so the correct retry must still work."""
    async def provider(tool_name, tool_args):
        return "HARDENED"

    proposer, verifier, _ = gate(provider)
    p = allowed(proposer)
    first = run(verifier.verify_commit(
        proposal_id=p["proposal_id"], commit_token=p["commit_token"],
        tool_name="place_trade", tool_args=ARGS, channel_profile="CHEAP",
    ))
    assert not first.ok and first.reason == CHANNEL_BELOW_REQUIRED_PROFILE
    retry = run(verifier.verify_commit(
        proposal_id=p["proposal_id"], commit_token=p["commit_token"],
        tool_name="place_trade", tool_args=ARGS, channel_profile="HARDENED",
    ))
    assert retry.ok, "a rejected channel must not spend the nonce"


def test_the_requirement_cannot_be_stripped_or_downgraded():
    """The field is inside the MAC, so editing it is a forgery (P3)."""
    async def provider(tool_name, tool_args):
        return "QUANTUM_SAFE"

    proposer, verifier, tm = gate(provider)
    p = allowed(proposer)
    payload_b64, sig_b64 = p["commit_token"].split(".", 1)
    payload = json.loads(base64.urlsafe_b64decode(payload_b64))

    for mutated in ({**payload, "required_cipher_profile": "CHEAP"},
                    {k: v for k, v in payload.items() if k != "required_cipher_profile"}):
        raw = json.dumps(mutated, sort_keys=True, separators=(",", ":")).encode()
        forged = f"{base64.urlsafe_b64encode(raw).decode()}.{sig_b64}"
        assert tm.verify(forged).reason == "bad_signature"


def test_provider_failure_binds_the_strongest_profile():
    """A policy service that could not be reached has not said 'unconstrained'."""
    async def provider(tool_name, tool_args):
        raise RuntimeError("memgraph unreachable")

    proposer, verifier, _ = gate(provider)
    p = allowed(proposer)
    payload = json.loads(base64.urlsafe_b64decode(p["commit_token"].split(".", 1)[0]))
    assert payload["required_cipher_profile"] == "QUANTUM_SAFE"
    weak = run(verifier.verify_commit(
        proposal_id=p["proposal_id"], commit_token=p["commit_token"],
        tool_name="place_trade", tool_args=ARGS, channel_profile="HARDENED",
    ))
    assert not weak.ok and weak.reason == CHANNEL_BELOW_REQUIRED_PROFILE


def test_provider_receives_the_call_it_is_deciding_about():
    seen = {}

    async def provider(tool_name, tool_args):
        seen["tool_name"], seen["tool_args"] = tool_name, tool_args
        return "CHEAP"

    proposer, _, _ = gate(provider)
    allowed(proposer, tool="transfer_funds", args=ARGS)
    assert seen == {"tool_name": "transfer_funds", "tool_args": ARGS}


def test_a_blocked_proposal_never_consults_the_provider():
    """A blocked proposal mints no token, so it has nothing to bind."""
    calls = []

    async def provider(tool_name, tool_args):
        calls.append(tool_name)
        return "CHEAP"

    proposer, _, _ = gate(provider)
    res = run(proposer.propose(
        tool_name="t", tool_args=ARGS, prompt="p",
        candidate_output_a="alpha beta gamma 1", candidate_output_b="delta epsilon 999",
    ))
    assert res["status"] == "blocked"
    assert calls == []


def test_strict_mode_refuses_a_token_carrying_no_requirement():
    proposer, verifier, _ = gate(require_binding=True)
    p = allowed(proposer)
    v = run(verifier.verify_commit(
        proposal_id=p["proposal_id"], commit_token=p["commit_token"],
        tool_name="place_trade", tool_args=ARGS, channel_profile="QUANTUM_SAFE",
    ))
    assert not v.ok and v.reason == CHANNEL_BELOW_REQUIRED_PROFILE
