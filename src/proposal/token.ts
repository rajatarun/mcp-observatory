import { createHmac, randomBytes } from 'crypto';
import { getCurrentTimeMs, addMs } from '../utils/time.js';

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

  constructor(secret?: string) {
    this.secret = secret ? Buffer.from(secret) : randomBytes(32);
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
