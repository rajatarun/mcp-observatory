import { TraceContext } from './context.js';
import { estimateTokens } from '../cost/tokenizer.js';
import { estimateCost } from '../cost/pricing.js';
import { hashText } from '../utils/hashing.js';
import { Tracer } from './tracer.js';

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

    try {
      output = await Promise.resolve(options.call());

      if (options.dualInvoke && options.shadowCall) {
        shadowOutput = await Promise.resolve(options.shadowCall());
      }
    } catch (error) {
      span.statusCode = 500;
      throw error;
    } finally {
      const outputText = JSON.stringify(output);
      span.outputHash = hashText(outputText);
      const outputTokens = estimateTokens(outputText, options.model);
      span.outputTokens = outputTokens;
      span.totalTokens = (span.inputTokens || 0) + outputTokens;
      span.costUsd = estimateCost(
        span.totalTokens,
        options.model || 'gpt-4',
        options.source
      );
      span.finish();
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
    return JSON.stringify(output);
  }
}
