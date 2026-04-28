import { Tracer } from '../core/tracer.js';
import { InvocationWrapper } from '../core/wrapper.js';

export class MCPClient {
  private tracer: Tracer;
  private wrapper: InvocationWrapper;

  constructor() {
    this.tracer = new Tracer('mcp-client');
    this.wrapper = new InvocationWrapper('mcp-client', {
      maxCostUsd: 0.5,
      maxLatencyMs: 10000,
    });
  }

  async invokeWithMetrics(options: {
    model: string;
    prompt: string;
    call: () => Promise<unknown>;
  }): Promise<unknown> {
    const result = await this.wrapper.invoke({
      source: 'agent',
      model: options.model,
      prompt: options.prompt,
      call: options.call,
    });

    console.log(`Decision: ${result.decision.action} (${result.decision.reason})`);
    console.log(`Cost: $${result.span.costUsd?.toFixed(4)}`);
    console.log(`Tokens: ${result.span.totalTokens}`);

    return result;
  }

  async dualMeasure(options: {
    model: string;
    prompt: string;
    primaryCall: () => Promise<unknown>;
    shadowCall: () => Promise<unknown>;
  }): Promise<unknown> {
    const result = await this.wrapper.invoke({
      source: 'agent',
      model: options.model,
      prompt: options.prompt,
      call: options.primaryCall,
      dualInvoke: true,
      shadowCall: options.shadowCall,
    });

    console.log('Dual Measurement:');
    console.log(`Primary Decision: ${result.decision.action}`);
    console.log(`Primary Cost: $${result.span.costUsd?.toFixed(4)}`);
    if (result.shadowSpan) {
      console.log(`Shadow Cost: $${result.shadowSpan.costUsd?.toFixed(4)}`);
    }

    return result;
  }
}

export async function runClientDemo(): Promise<void> {
  const client = new MCPClient();

  console.log('=== MCP Client Demo ===\n');

  await client.invokeWithMetrics({
    model: 'gpt-4o-mini',
    prompt: 'Generate a deployment plan for a microservices application',
    call: async () => ({
      plan: 'blue-green rollout with canary validation',
      steps: [
        'Deploy to staging',
        'Run smoke tests',
        'Deploy to production',
      ],
    }),
  });
}
