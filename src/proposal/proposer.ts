import { normaliseProfile, STRONGEST_PROFILE } from './channel.js';
import { randomUUID } from 'crypto';
import { hashJson } from '../utils/hashing.js';
import { argsExceedLimit } from '../utils/limits.js';
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

/** A composite score, plus how many signals informed it. */
export interface CompositeScore {
  /** `undefined` when no signal was supplied — not zero. */
  score: number | undefined;
  definedCount: number;
}

export interface ScoringOptions {
  outputInstability?: number;
  numericVariance?: number;
  promptDrift?: number;
}

export type ChannelProfileProvider = (
  toolName: string,
  toolArgs: Record<string, unknown>,
) => Promise<string> | string;

export class ToolProposer {
  private tokenManager: TokenManager;
  private blockThreshold: number = 0.7;
  private reviewThreshold: number = 0.4;
  private channelProfileProvider?: ChannelProfileProvider;

  /**
   * `channelProfileProvider` names the channel strength a call must run over
   * (gate property P6). It is injected rather than imported: this package is a
   * dependency of several unrelated products, most of which run no channel
   * policy, so importing the service that produces the profile would make
   * every consumer depend on it.
   *
   * Absent, nothing is bound and behaviour is unchanged. Present but throwing,
   * the call is bound to the strongest profile — a policy service that could
   * not be reached has not said "unconstrained".
   */
  constructor(tokenManager?: TokenManager, options?: { channelProfileProvider?: ChannelProfileProvider }) {
    this.tokenManager = tokenManager || new TokenManager();
    this.channelProfileProvider = options?.channelProfileProvider;
  }

  /** Ask the channel policy what this call needs; fail secure if it cannot say. */
  private async requiredChannelProfile(
    toolName: string,
    toolArgs: Record<string, unknown>,
  ): Promise<string | undefined> {
    if (!this.channelProfileProvider) return undefined;
    try {
      return normaliseProfile(await this.channelProfileProvider(toolName, toolArgs));
    } catch {
      return STRONGEST_PROFILE;
    }
  }

  async propose(options: ProposalOptions): Promise<ProposalResult> {
    const proposalId = randomUUID();

    // Cost is linear in input size and the gate cannot bound its own latency,
    // so refuse before hashing rather than after (see utils/limits.ts).
    if (argsExceedLimit(options.toolArgs)) {
      return {
        proposalId,
        status: 'blocked',
        reason: 'input_too_large',
        fallbackResponse: this.deterministicFallback(options.toolName, options.toolArgs),
      };
    }

    const toolArgsHash = hashJson(options.toolArgs);
    const { score, definedCount } = this.computeCompositeScore({
      outputInstability: options.outputInstability,
      numericVariance: options.numericVariance,
      promptDrift: options.promptDrift,
    });

    // No computable signal is not zero risk. Refuse rather than allow, and
    // refuse rather than `review`: a `review` result still issues a usable
    // commit token here, so it is not a refusal.
    if (score === undefined) {
      return {
        proposalId,
        status: 'blocked',
        reason: 'no_signals',
        fallbackResponse: this.deterministicFallback(options.toolName, options.toolArgs),
      };
    }

    const compositeScore = score;
    void definedCount;

    if (compositeScore > this.blockThreshold) {
      return {
        proposalId,
        status: 'blocked',
        reason: 'low_integrity',
        fallbackResponse: this.deterministicFallback(options.toolName, options.toolArgs),
      };
    }

    if (compositeScore > this.reviewThreshold) {
      // `review` mints a usable token in this package, unlike the Python line
      // where only `allow` does, so it must carry the same binding. An
      // unbound review token would be a way around P6, not a lesser form of it.
      const requiredCipherProfile = await this.requiredChannelProfile(
        options.toolName, options.toolArgs,
      );
      const { token } = this.tokenManager.issueToken({
        proposalId,
        toolName: options.toolName,
        toolArgsHash,
        compositeScore,
        requiredCipherProfile,
      });

      return {
        proposalId,
        status: 'review',
        commitToken: token,
      };
    }

    const requiredCipherProfile = await this.requiredChannelProfile(
      options.toolName, options.toolArgs,
    );
    const { token } = this.tokenManager.issueToken({
      proposalId,
      toolName: options.toolName,
      toolArgsHash,
      compositeScore,
      requiredCipherProfile,
    });

    return {
      proposalId,
      status: 'allowed',
      commitToken: token,
    };
  }

  /**
   * Weighted mean over the signals that were actually supplied.
   *
   * Returns `undefined` when none was, which is not the same as zero. The
   * previous form read each optional signal as `value || 0` and divided by a
   * fixed denominator of 1.0, so an absent signal contributed no risk at full
   * weight: a proposal carrying no signals at all scored 0 and was allowed,
   * with a commit token. That is the fail-open this renormalisation exists to
   * prevent — missing evidence must not read as evidence of safety — and it
   * was reachable from the ordinary API, since all three signals are optional
   * parameters.
   *
   * `|| 0` also conflated a genuine instability of 0 with an absent one. The
   * explicit `undefined` check keeps a real zero in the defined set.
   */
  private computeCompositeScore(scoring: ScoringOptions): CompositeScore {
    const weights = {
      instability: 0.5,
      variance: 0.3,
      drift: 0.2,
    };

    const supplied: Array<[number | undefined, number]> = [
      [scoring.outputInstability, weights.instability],
      [scoring.numericVariance, weights.variance],
      [scoring.promptDrift, weights.drift],
    ];

    let weightedSum = 0;
    let totalWeight = 0;
    let definedCount = 0;

    for (const [value, weight] of supplied) {
      if (value === undefined || value === null || Number.isNaN(value)) continue;
      weightedSum += Math.max(0, Math.min(1, value)) * weight;
      totalWeight += weight;
      definedCount += 1;
    }

    if (totalWeight === 0) {
      return { score: undefined, definedCount: 0 };
    }

    return {
      score: Math.max(0, Math.min(1, weightedSum / totalWeight)),
      definedCount,
    };
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
