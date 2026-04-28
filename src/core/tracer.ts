import { TraceContext } from './context.js';

export class Tracer {
  constructor(readonly service: string) {}

  startSpan(options?: {
    model?: string;
    toolName?: string;
    parent?: TraceContext;
  }): TraceContext {
    return new TraceContext({
      service: this.service,
      model: options?.model,
      toolName: options?.toolName,
      traceId: options?.parent?.traceId,
      parentSpanId: options?.parent?.spanId,
    });
  }

  endSpan(span: TraceContext): TraceContext {
    span.finish();
    return span;
  }

  async withSpan<T>(
    fn: (span: TraceContext) => Promise<T> | T,
    options?: { model?: string; toolName?: string; parent?: TraceContext }
  ): Promise<T> {
    const span = this.startSpan(options);
    try {
      return await fn(span);
    } finally {
      this.endSpan(span);
    }
  }
}
