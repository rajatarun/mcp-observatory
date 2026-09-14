import { randomUUID } from 'crypto';

export interface TraceSpan {
  spanId: string;
  traceId: string;
  parentSpanId?: string;
  service: string;
  /**
   * The kind of call this span represents ("invoke_model", "invoke_agent",
   * "invoke_tool", ...). Every consumer of this package had invented its own
   * copy of this concept in a hand-rolled exporter, which is a large part of
   * why the shared metrics table ended up with several row shapes. It belongs
   * on the span so there is one spelling of it.
   */
  operation?: string;
  model?: string;
  toolName?: string;
  startTime: Date;
  endTime?: Date;
  inputHash?: string;
  outputHash?: string;
  inputTokens?: number;
  outputTokens?: number;
  totalTokens?: number;
  costUsd?: number;
  statusCode?: number;
  tags?: Record<string, string | number | boolean>;
}

export class TraceContext {
  readonly spanId: string;
  readonly traceId: string;
  readonly parentSpanId?: string;
  readonly service: string;
  readonly operation?: string;
  readonly model?: string;
  readonly toolName?: string;
  readonly startTime: Date;
  endTime?: Date;
  inputHash?: string;
  outputHash?: string;
  inputTokens?: number;
  outputTokens?: number;
  totalTokens?: number;
  costUsd: number = 0;
  statusCode?: number;
  tags: Record<string, string | number | boolean> = {};

  constructor(options: {
    service: string;
    operation?: string;
    model?: string;
    toolName?: string;
    traceId?: string;
    parentSpanId?: string;
  }) {
    this.spanId = randomUUID();
    this.traceId = options.traceId || randomUUID();
    this.parentSpanId = options.parentSpanId;
    this.service = options.service;
    this.operation = options.operation;
    this.model = options.model;
    this.toolName = options.toolName;
    this.startTime = new Date();
  }

  finish(): void {
    this.endTime = new Date();
  }

  toJSON(): TraceSpan {
    return {
      spanId: this.spanId,
      traceId: this.traceId,
      parentSpanId: this.parentSpanId,
      service: this.service,
      operation: this.operation,
      model: this.model,
      toolName: this.toolName,
      startTime: this.startTime,
      endTime: this.endTime,
      inputHash: this.inputHash,
      outputHash: this.outputHash,
      inputTokens: this.inputTokens,
      outputTokens: this.outputTokens,
      totalTokens: this.totalTokens,
      costUsd: this.costUsd,
      statusCode: this.statusCode,
      tags: this.tags,
    };
  }
}
