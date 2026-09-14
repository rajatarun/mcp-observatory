import { CHANNEL_BELOW_REQUIRED_PROFILE, channelSatisfies } from './channel.js';
import { hashJson } from '../utils/hashing.js';
import { TokenManager } from './token.js';

export interface VerificationOptions {
  token: string;
  proposalId: string;
  toolName: string;
  toolArgs: Record<string, unknown>;
  /**
   * The channel strength the executor claims this call is running over.
   * Checked against the requirement bound into the token (P6). Omitting it
   * when the token carries a requirement is itself a refusal: the gate binds
   * the executor's *claim*, and an executor that makes no claim has not
   * established anything.
   */
  channelProfile?: string;
}

export interface VerificationResult {
  valid: boolean;
  reason?: string;
  canExecute: boolean;
}

export class CommitVerifier {
  private tokenManager: TokenManager;
  private usedNonces: Set<string> = new Set();
  private requireChannelBinding: boolean;

  /**
   * `requireChannelBinding` refuses any token that carries no requirement at
   * all. Off by default, because most deployments run no channel policy and
   * their tokens legitimately carry nothing to enforce; on, for a deployment
   * that wants every commit to have been through one.
   */
  constructor(tokenManager?: TokenManager, options?: { requireChannelBinding?: boolean }) {
    this.tokenManager = tokenManager || new TokenManager();
    this.requireChannelBinding = options?.requireChannelBinding ?? false;
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

    // P6, and its position matters: this sits AFTER the args hash check but
    // BEFORE the nonce is inspected or burned. A call refused for running over
    // too weak a channel has not been executed, so it must stay retryable over
    // a stronger one; burning the nonce here would turn a recoverable refusal
    // into a permanently dead authorisation.
    const required = payload.requiredCipherProfile;
    if (required === undefined) {
      if (this.requireChannelBinding) {
        return { valid: false, reason: CHANNEL_BELOW_REQUIRED_PROFILE, canExecute: false };
      }
    } else if (!channelSatisfies(options.channelProfile, required)) {
      return { valid: false, reason: CHANNEL_BELOW_REQUIRED_PROFILE, canExecute: false };
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
