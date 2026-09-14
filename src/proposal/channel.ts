/**
 * Channel binding: the commit token carries the channel strength a call must run over.
 *
 * Port of the Python line's `proposal_commit/channel.py` (gate property P6).
 * The property it enforces is that an executor cannot quietly downgrade the
 * transport for a call that was authorised on the assumption of a strong one.
 *
 * The profile names are duplicated here rather than imported from CipherWeave,
 * which is the service that produces them. That is deliberate, and it is the
 * same call the Python line made: this package is a dependency of several
 * unrelated products, most of which run no channel policy at all. Importing
 * the producer would make every consumer depend on it, and an ImportError
 * inside the gate would fail closed for a deployment that never asked for the
 * feature. The profile lattice is four strings that have not changed; the
 * coupling would cost more than the duplication.
 */

/** Ordered weakest to strongest. A higher number satisfies a lower requirement. */
export const PROFILE_STRENGTH: Record<string, number> = {
  CHEAP: 0,
  BALANCED: 1,
  HARDENED: 2,
  QUANTUM_SAFE: 3,
};

export const STRONGEST_PROFILE = 'QUANTUM_SAFE';

export const CHANNEL_BELOW_REQUIRED_PROFILE = 'channel_below_required_profile';

/**
 * Coerce a value to a known profile, failing secure.
 *
 * Anything unrecognised — undefined, empty, a typo, a number — becomes the
 * strongest profile rather than the weakest. A value the gate cannot place is
 * not evidence that a weak channel is acceptable.
 */
export function normaliseProfile(value: unknown): string {
  if (typeof value !== 'string') return STRONGEST_PROFILE;
  const key = value.trim().toUpperCase();
  return key in PROFILE_STRENGTH ? key : STRONGEST_PROFILE;
}

/**
 * Does the channel the executor claims to be using satisfy what was required?
 *
 * An unplaceable channel satisfies nothing: absence of a signal is not a
 * signal of strength. An unrecognised *requirement* is enforced at maximum,
 * so a corrupted-but-signed profile refuses the call rather than waving it
 * through.
 */
export function channelSatisfies(channelProfile: unknown, required: unknown): boolean {
  const channelKey = typeof channelProfile === 'string' ? channelProfile.trim().toUpperCase() : '';
  const channelRank = PROFILE_STRENGTH[channelKey];
  if (channelRank === undefined) return false;

  const requiredKey = typeof required === 'string' ? required.trim().toUpperCase() : '';
  const requiredRank = requiredKey in PROFILE_STRENGTH
    ? PROFILE_STRENGTH[requiredKey]
    : PROFILE_STRENGTH[STRONGEST_PROFILE];

  return channelRank >= requiredRank;
}
