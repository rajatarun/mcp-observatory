/**
 * Input-size ceiling applied before anything expensive touches a payload.
 *
 * Every step of the gate is linear in the size of its input — canonical JSON
 * serialisation, SHA-256 hashing, the signal computations — so the gate cannot
 * bound its own latency. A caller (or an attacker) handing it a multi-megabyte
 * argument mapping buys multi-megabyte hashing on the request path.
 *
 * The control therefore has to sit *upstream of scoring*: refuse the call
 * before hashing rather than after. This mirrors the Python line's P5, where
 * the same bound is documented in `docs/gate-properties.md` and the same
 * `MCP_OBSERVATORY_MAX_INPUT_BYTES` variable names the ceiling.
 *
 * Read from the environment on each call rather than cached at module load, so
 * a test or a host can change it without re-importing the module.
 */

export const MAX_INPUT_BYTES_ENV = 'MCP_OBSERVATORY_MAX_INPUT_BYTES';

/** Default ceiling, in bytes. Matches the Python package's default. */
export const DEFAULT_MAX_INPUT_BYTES = 10240;

export function maxInputBytes(): number {
  const raw = process.env[MAX_INPUT_BYTES_ENV];
  if (raw === undefined || raw === '') return DEFAULT_MAX_INPUT_BYTES;
  const parsed = Number(raw);
  // A malformed ceiling must not silently disable the limit.
  if (!Number.isFinite(parsed) || parsed <= 0) return DEFAULT_MAX_INPUT_BYTES;
  return Math.floor(parsed);
}

/** True when `value`'s UTF-8 length exceeds the configured ceiling. */
export function exceedsLimit(value: string | undefined | null): boolean {
  if (value === undefined || value === null) return false;
  return Buffer.byteLength(value, 'utf8') > maxInputBytes();
}

/**
 * True when any argument mapping is over the ceiling.
 *
 * Serialising to measure is itself linear, but it is one pass with no hashing
 * and no signal work behind it, which is the cost the ceiling exists to avoid.
 * A value that cannot be serialised at all (a circular reference, a BigInt) is
 * treated as over the limit: the gate cannot hash what it cannot serialise, so
 * refusing is the fail-secure reading rather than proceeding to a crash.
 */
export function argsExceedLimit(args: unknown): boolean {
  let serialised: string;
  try {
    serialised = JSON.stringify(args) ?? '';
  } catch {
    return true;
  }
  return exceedsLimit(serialised);
}
