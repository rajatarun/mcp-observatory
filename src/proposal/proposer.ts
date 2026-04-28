import { randomUUID } from 'crypto';
import { hashJson } from '../utils/hashing.js';
import { TokenManager } from './token.js';

export interface ProposalOptions {
  toolName: string;
  toolArgs: Record<string, unknown>;
  outputInstability?: number;
  numericVariance?: number;
  promptDrift?: number;
}

export interface ProposalResult {
  proposalId: string;
  status: 'allowed' | 'blocked' | 'review';
  reason?: string;
  commitToken?: string;
  fallbackResponse?: unknown;
}

export interface ScoringOptions {
  outputInstability?: number;
  numericVariance?: number;
  promptDrift?: number;
}

export class ToolProposer {
  private tokenManager: TokenManager;
  private blockThreshold: number = 0.7;
  private reviewThreshold: number = 0.4;

  constructor(tokenManager?: TokenManager) {
    this.tokenManager = tokenManager || new TokenManager();
  }

  async propose(options: ProposalOptions): Promise<ProposalResult> {
    const proposalId = randomUUID();
    const toolArgsHash = hashJson(options.toolArgs);
    const compositeScore = this.computeCompositeScore({
      outputInstability: options.outputInstability,
      numericVariance: options.numericVariance,
      promptDrift: options.promptDrift,
    });

    if (compositeScore > this.blockThreshold) {
      return {
        proposalId,
        status: 'blocked',
        reason: 'low_integrity',
        fallbackResponse: this.deterministicFallback(options.toolName, options.toolArgs),
      };
    }

    if (compositeScore > this.reviewThreshold) {
      const { token } = this.tokenManager.issueToken({
        proposalId,
        toolName: options.toolName,
        toolArgsHash,
        compositeScore,
      });

      return {
        proposalId,
        status: 'review',
        commitToken: token,
      };
    }

    const { token } = this.tokenManager.issueToken({
      proposalId,
      toolName: options.toolName,
      toolArgsHash,
      compositeScore,
    });

    return {
      proposalId,
      status: 'allowed',
      commitToken: token,
    };
  }

  private computeCompositeScore(scoring: ScoringOptions): number {
    const instability = Math.max(0, Math.min(1, scoring.outputInstability || 0));
    const variance = Math.max(0, Math.min(1, scoring.numericVariance || 0));
    const drift = Math.max(0, Math.min(1, scoring.promptDrift || 0));

    const weights = {
      instability: 0.5,
      variance: 0.3,
      drift: 0.2,
    };

    return (
      instability * weights.instability +
      variance * weights.variance +
      drift * weights.drift
    );
  }

  private deterministicFallback(
    toolName: string,
    toolArgs: Record<string, unknown>
  ): unknown {
    return {
      status: 'blocked',
      action: 'create_draft',
      reason: 'low_integrity',
      draft: { tool: toolName, ...toolArgs },
    };
  }
}
