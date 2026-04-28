import { hashJson } from '../utils/hashing.js';
import { TokenManager } from './token.js';

export interface VerificationOptions {
  token: string;
  proposalId: string;
  toolName: string;
  toolArgs: Record<string, unknown>;
}

export interface VerificationResult {
  valid: boolean;
  reason?: string;
  canExecute: boolean;
}

export class CommitVerifier {
  private tokenManager: TokenManager;
  private usedNonces: Set<string> = new Set();

  constructor(tokenManager?: TokenManager) {
    this.tokenManager = tokenManager || new TokenManager();
  }

  verify(options: VerificationOptions): VerificationResult {
    const tokenResult = this.tokenManager.verifyToken(options.token);
    if (!tokenResult.valid) {
      return { valid: false, reason: tokenResult.reason, canExecute: false };
    }

    const payload = tokenResult.payload!;

    if (payload.proposalId !== options.proposalId) {
      return { valid: false, reason: 'unknown_proposal', canExecute: false };
    }

    if (payload.toolName !== options.toolName) {
      return { valid: false, reason: 'tool_name_mismatch', canExecute: false };
    }

    const argsHash = hashJson(options.toolArgs);
    if (argsHash !== payload.toolArgsHash) {
      return { valid: false, reason: 'args_hash_mismatch', canExecute: false };
    }

    if (this.usedNonces.has(payload.nonce)) {
      return { valid: false, reason: 'nonce_replay', canExecute: false };
    }

    this.usedNonces.add(payload.nonce);
    return { valid: true, canExecute: true };
  }

  resetNonces(): void {
    this.usedNonces.clear();
  }
}
