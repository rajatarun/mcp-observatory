import { createHmac, randomBytes } from 'crypto';
import { getCurrentTimeMs, addMs } from '../utils/time.js';
import {
  COMMIT_SECRET_ENV,
  DEV_COMMIT_SECRET,
  resolveSecret,
} from '../utils/secrets.js';

export interface TokenPayload {
  tokenId: string;
  proposalId: string;
  toolName: string;
  toolArgsHash: string;
  issuedAt: number;
  expiresAt: number;
  nonce: string;
  compositeScore: number;
}

export interface TokenVerificationResult {
  valid: boolean;
  reason?: string;
  payload?: TokenPayload;
}

/** A token string that decodes, but not from its one canonical spelling. */
export class NonCanonicalTokenError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'NonCanonicalTokenError';
    Object.setPrototypeOf(this, NonCanonicalTokenError.prototype);
  }
}

/**
 * Decode a token, accepting only the exact string the issuer would produce.
 *
 * The HMAC covers the payload's *values*, not the token *string*, and both
 * layers of the encoding are lenient, so one authorisation had unboundedly
 * many accepted spellings:
 *
 * - Node's base64 decoder silently drops characters outside the alphabet,
 *   so `token + "!"`, `token + "=="`, a trailing newline and whitespace
 *   injected anywhere in the middle all decoded to identical bytes and
 *   verified.
 * - The signature is recomputed from the re-serialised payload object
 *   rather than from the received bytes, so any JSON spelling that parses
 *   to the same object verified too — a pretty-printed payload, or one
 *   with a space after `{`.
 *
 * Replay is still caught either way, because the nonce is inside the
 * signed payload. The cost is in anything keyed on the token string: a
 * caller that records `sha256(token)` on a span or an audit row would file
 * one authorisation under arbitrarily many hashes, and a nonce cache keyed
 * on the string rather than on `payload.nonce` would not catch a replay at
 * all.
 *
 * Requiring both round-trips — re-encoding the bytes must reproduce the
 * base64, and re-serialising the object must reproduce the JSON — makes
 * the token string canonical, so `sha256(token)` identifies exactly one
 * authorisation. This is the same property the Python line states as P3 in
 * `docs/gate-properties.md`; note the encoding here is plain base64, not
 * the base64url Python uses, so the re-encode is checked against the
 * padded standard alphabet that `issueToken` emits.
 */
function decodeCanonicalToken(token: string): TokenPayload & { signature: string } {
  const raw = Buffer.from(token, 'base64');
  if (raw.toString('base64') !== token) {
    throw new NonCanonicalTokenError('token is not canonical base64');
  }

  const json = raw.toString('utf8');
  const data = JSON.parse(json) as TokenPayload & { signature: string };
  if (data === null || typeof data !== 'object' || Array.isArray(data)) {
    throw new NonCanonicalTokenError('token payload is not an object');
  }
  if (JSON.stringify(data) !== json) {
    throw new NonCanonicalTokenError('token payload is not canonical JSON');
  }

  return data;
}

export class TokenManager {
  private secret: Buffer;
  private tokenExpiryMs: number = 300000; // 5 minutes

  /**
   * @param secret HMAC key for commit tokens. Falls back to
   * `MCP_OBSERVATORY_COMMIT_SECRET`. Throws `InsecureDefaultSecretError`
   * when neither is set, unless `MCP_OBSERVATORY_ALLOW_DEV_SECRET=1`.
   *
   * This used to default to `randomBytes(32)`, which made the key
   * per-instance: a restarted or scaled-out process could not verify a
   * token it had issued, and the proposer and the verifier — each of which
   * builds its own `TokenManager` when none is supplied — never shared a
   * key at all. Both failures surfaced as `bad_signature`, which is what a
   * forgery looks like, so missing configuration was indistinguishable
   * from an attack. Resolving the secret explicitly moves that failure to
   * construction time, where the message can name the cause.
   */
  constructor(secret?: string) {
    this.secret = Buffer.from(
      resolveSecret(secret, {
        envVar: COMMIT_SECRET_ENV,
        devDefault: DEV_COMMIT_SECRET,
        label: COMMIT_SECRET_ENV,
      }),
      'utf8'
    );
  }

  issueToken(options: {
    proposalId: string;
    toolName: string;
    toolArgsHash: string;
    compositeScore: number;
    expiryMs?: number;
  }): { token: string; payload: TokenPayload } {
    const now = getCurrentTimeMs();
    const expiryMs = options.expiryMs || this.tokenExpiryMs;

    const payload: TokenPayload = {
      tokenId: this.randomId(),
      proposalId: options.proposalId,
      toolName: options.toolName,
      toolArgsHash: options.toolArgsHash,
      issuedAt: now,
      expiresAt: addMs(new Date(now), expiryMs).getTime(),
      nonce: randomBytes(16).toString('hex'),
      compositeScore: options.compositeScore,
    };

    const signature = this.sign(payload);
    const token = Buffer.from(
      JSON.stringify({ ...payload, signature })
    ).toString('base64');

    return { token, payload };
  }

  verifyToken(token: string): TokenVerificationResult {
    let data: TokenPayload & { signature: string };
    try {
      data = decodeCanonicalToken(token);
    } catch (error) {
      if (error instanceof NonCanonicalTokenError) {
        return { valid: false, reason: 'non_canonical_token' };
      }
      return { valid: false, reason: 'invalid_token_format' };
    }

    try {
      const { signature, ...payload } = data;

      if (!signature) {
        return { valid: false, reason: 'missing_signature' };
      }

      if (this.sign(payload as TokenPayload) !== signature) {
        return { valid: false, reason: 'bad_signature' };
      }

      if (payload.expiresAt < getCurrentTimeMs()) {
        return { valid: false, reason: 'expired' };
      }

      return { valid: true, payload: payload as TokenPayload };
    } catch {
      return { valid: false, reason: 'invalid_token_format' };
    }
  }

  private sign(payload: TokenPayload): string {
    const data = JSON.stringify(payload);
    return createHmac('sha256', this.secret).update(data).digest('hex');
  }

  private randomId(): string {
    return randomBytes(8).toString('hex');
  }
}
