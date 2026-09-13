import { TraceContext } from './context.js';
import { estimateTokens } from '../cost/tokenizer.js';
import { estimateCost } from '../cost/pricing.js';
import { hashText } from '../utils/hashing.js';
import { Tracer } from './tracer.js';

/**
 * JSON.stringify() is not a total function: it throws for BigInt values and
 * for circular references, and it returns the *value* `undefined` (not a
 * string) when given `undefined`. Span bookkeeping must never throw on
 * account of what a wrapped call happened to return, so fall back to
 * String() -- and finally to a fixed placeholder -- for anything
 * JSON.stringify can't turn into a string.
 */
function safeStringifyForSpan(value: unknown): string {
  try {
    const json = JSON.stringify(value);
    if (typeof json === 'string') {
      return json;
    }
  } catch {
    // fall through to the String() fallback below
  }
  try {
    return String(value);
  } catch {
    return '[unserializable]';
  }
}

export interface WrapperDecision {
  action: 'allow' | 'review' | 'block';
  reason?: string;
  metadata?: Record<string, unknown>;
}

export interface WrapperPolicy {
  maxCostUsd?: number;
  maxLatencyMs?: number;
}

export interface WrapperResult {
  output: unknown;
  span: TraceContext;
  decision: WrapperDecision;
  shadowOutput?: unknown;
  shadowSpan?: TraceContext;
}

export class InvocationWrapper {
  private tracer: Tracer;
  private policy: Required<WrapperPolicy>;

  constructor(service: string, policy?: WrapperPolicy) {
    this.tracer = new Tracer(service);
    this.policy = {
      maxCostUsd: policy?.maxCostUsd ?? 0.25,
      maxLatencyMs: policy?.maxLatencyMs ?? 8000,
    };
  }

  async invoke(options: {
    source: 'agent' | 'model';
    model?: string;
    prompt: string;
    inputPayload?: Record<string, unknown>;
    call: () => Promise<unknown> | unknown;
    dualInvoke?: boolean;
    shadowCall?: () => Promise<unknown> | unknown;
  }): Promise<WrapperResult> {
    const span = this.tracer.startSpan({
      model: options.model,
    });

    const inputText = options.prompt + JSON.stringify(options.inputPayload || {});
    span.inputHash = hashText(inputText);
    const tokens = estimateTokens(inputText, options.model);
    span.inputTokens = tokens;

    const startTime = Date.now();
    let output: unknown;
    let shadowOutput: unknown;
    let callFailed = false;

    try {
      output = await Promise.resolve(options.call());

      if (options.dualInvoke && options.shadowCall) {
        shadowOutput = await Promise.resolve(options.shadowCall());
      }
    } catch (error) {
      callFailed = true;
      span.statusCode = 500;
      throw error;
    } finally {
      // Span finalisation must never throw: this runs inside the try/catch's
      // finally, so an exception here (e.g. hashText(undefined) when a
      // rejected call() left `output` unset, or JSON.stringify choking on a
      // BigInt/circular output) would replace whatever the catch block above
      // just threw, hiding the caller's real error behind an unrelated
      // TypeError. Telemetry for a failed call still matters, so we still
      // finish and export the span on that path -- just without an output
      // hash/tokens -- and any unexpected error while computing metrics is
      // swallowed rather than allowed to propagate.
      try {
        if (callFailed) {
          span.outputTokens = 0;
          span.totalTokens = span.inputTokens || 0;
        } else {
          const outputText = safeStringifyForSpan(output);
          span.outputHash = hashText(outputText);
          const outputTokens = estimateTokens(outputText, options.model);
          span.outputTokens = outputTokens;
          span.totalTokens = (span.inputTokens || 0) + outputTokens;
        }
        span.costUsd = estimateCost(
          span.totalTokens,
          options.model || 'gpt-4',
          options.source
        );
      } catch (finalizationError) {
        console.error(
          '[mcp-observatory] span finalisation failed; continuing without output hash/tokens',
          finalizationError
        );
      } finally {
        span.finish();
      }
    }

    const decision = this.decide(span, output);

    const result: WrapperResult = {
      output,
      span,
      decision,
    };

    if (options.dualInvoke && shadowOutput !== undefined) {
      const shadowSpan = this.tracer.startSpan({ model: options.model });
      const shadowText = JSON.stringify(shadowOutput);
      shadowSpan.outputHash = hashText(shadowText);
      shadowSpan.outputTokens = estimateTokens(shadowText, options.model);
      shadowSpan.finish();
      result.shadowOutput = shadowOutput;
      result.shadowSpan = shadowSpan;
    }

    return result;
  }

  private decide(span: TraceContext, output: unknown): WrapperDecision {
    if (!span.endTime) {
      throw new Error('Span must be completed before decisioning');
    }

    const latencyMs = span.endTime.getTime() - span.startTime.getTime();
    const outputText = this.toText(output);

    if (!outputText.trim()) {
      return { action: 'block', reason: 'empty_output' };
    }

    if (span.costUsd > this.policy.maxCostUsd) {
      return {
        action: 'review',
        reason: 'cost_budget_exceeded',
        metadata: { costUsd: span.costUsd, maxCostUsd: this.policy.maxCostUsd },
      };
    }

    if (latencyMs > this.policy.maxLatencyMs) {
      return {
        action: 'review',
        reason: 'latency_budget_exceeded',
        metadata: { latencyMs: Math.round(latencyMs), maxLatencyMs: this.policy.maxLatencyMs },
      };
    }

    return { action: 'allow', reason: 'within_budget' };
  }

  private toText(output: unknown): string {
    if (typeof output === 'string') return output;
    if (output === null || output === undefined) return '';
    return safeStringifyForSpan(output);
  }
}
