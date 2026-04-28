const PRICING: Record<string, { input: number; output: number }> = {
  'gpt-4': { input: 0.03, output: 0.06 },
  'gpt-4-turbo': { input: 0.01, output: 0.03 },
  'gpt-4o': { input: 0.005, output: 0.015 },
  'gpt-4o-mini': { input: 0.00015, output: 0.0006 },
  'claude-3-opus': { input: 0.015, output: 0.075 },
  'claude-3-sonnet': { input: 0.003, output: 0.015 },
  'claude-3-haiku': { input: 0.00025, output: 0.00125 },
};

export function estimateCost(
  totalTokens: number,
  model: string = 'gpt-4',
  source: 'agent' | 'model' = 'model'
): number {
  const pricing = PRICING[model] || PRICING['gpt-4'];

  const inputTokens = Math.ceil(totalTokens * 0.5);
  const outputTokens = totalTokens - inputTokens;

  const inputCost = (inputTokens / 1000) * pricing.input;
  const outputCost = (outputTokens / 1000) * pricing.output;

  return inputCost + outputCost;
}

export function getPricing(model: string): { input: number; output: number } {
  return PRICING[model] || PRICING['gpt-4'];
}
