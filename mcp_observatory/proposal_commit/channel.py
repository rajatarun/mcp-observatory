"""Channel-strength binding for commit tokens.

The gate decides *whether* a call runs. A separate policy service can decide
*how strongly the channel it runs over must be protected* — CipherWeave is the
one this was designed against. Binding that decision into the commit token
means an executor cannot silently downgrade the transport for a call that was
authorised on the assumption of a strong one.

Why this module imports nothing
-------------------------------
The profile names and their order are duplicated here rather than imported from
the policy service that produces them. That is deliberate. This library is a
general-purpose dependency of five unrelated products, and most deployments run
no channel policy at all; importing the policy service would make every one of
them depend on it, and an ImportError in the verifier would fail *closed* for a
deployment that never asked for the feature.

The four names and their ordering are therefore a contract between the two
systems, not a shared symbol. If that contract ever has to change, it needs a
version field in the token — not a shared import.
"""
from __future__ import annotations

#: Rejection reason: the executor's channel is weaker than the profile bound
#: into the token. Distinct from ``args_hash_mismatch`` (the call *is* the call
#: that was scored) and from ``bad_signature`` (the token is authentic) — what
#: differs is the channel the executor proposes to run it over.
CHANNEL_BELOW_REQUIRED_PROFILE = "channel_below_required_profile"

#: Total order over channel strength. Higher is stronger.
PROFILE_STRENGTH: dict[str, int] = {
    "CHEAP": 0,
    "BALANCED": 1,
    "HARDENED": 2,
    "QUANTUM_SAFE": 3,
}

#: The strongest profile, used wherever a requirement cannot be determined.
STRONGEST_PROFILE = "QUANTUM_SAFE"


def channel_satisfies(channel_profile: str | None, required: str) -> bool:
    """True when the executor's channel meets or exceeds ``required``.

    Unknown, unparseable and absent channels satisfy nothing. A channel the
    verifier cannot place on the lattice is not evidence of a strong channel,
    and treating it as one would be the same fail-open the composite score's
    renormalisation exists to prevent (see ``docs/gate-properties.md`` P2).

    A ``required`` value that is not on the lattice is enforced at maximum
    strength rather than ignored, so a corrupted-but-authentically-signed
    profile refuses rather than waves the call through.
    """
    actual = PROFILE_STRENGTH.get(str(channel_profile or "").strip().upper())
    if actual is None:
        return False
    needed = PROFILE_STRENGTH.get(str(required).strip().upper(), PROFILE_STRENGTH[STRONGEST_PROFILE])
    return actual >= needed


def normalise_profile(value: object) -> str:
    """Coerce a provider's answer onto the lattice, failing secure.

    Anything unrecognised becomes the strongest profile: a policy service that
    returned something this library cannot interpret has not said "unconstrained".
    """
    candidate = str(value or "").strip().upper()
    return candidate if candidate in PROFILE_STRENGTH else STRONGEST_PROFILE
