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
    try {
      const data = JSON.parse(Buffer.from(token, 'base64').toString());
      const { signature, ...payload } = data as TokenPayload & { signature: string };

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
