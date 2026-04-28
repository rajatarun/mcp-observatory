const TOKENS_PER_WORD = 1.3;
const TOKENS_PER_CHAR = 0.25;

const MODEL_TOKEN_LIMITS: Record<string, { input: number; output: number }> = {
  'gpt-4': { input: 8191, output: 8191 },
  'gpt-4-turbo': { input: 128000, output: 4096 },
  'gpt-4o': { input: 128000, output: 4096 },
  'gpt-4o-mini': { input: 128000, output: 4096 },
  'claude-3-opus': { input: 200000, output: 4096 },
  'claude-3-sonnet': { input: 200000, output: 4096 },
  'claude-3-haiku': { input: 200000, output: 1024 },
};

export function estimateTokens(text: string, model?: string): number {
  const wordCount = text.split(/\s+/).length;
  const charCount = text.length;

  const fromWords = Math.ceil(wordCount * TOKENS_PER_WORD);
  const fromChars = Math.ceil(charCount * TOKENS_PER_CHAR);

  return Math.max(fromWords, fromChars);
}

export function getTokenLimits(model: string): { input: number; output: number } {
  return MODEL_TOKEN_LIMITS[model] || { input: 4096, output: 2048 };
}

export function estimateCompletionTokens(input: string, estimatedOutputLength: number): number {
  return estimateTokens(input) + Math.ceil(estimatedOutputLength * TOKENS_PER_CHAR);
}
