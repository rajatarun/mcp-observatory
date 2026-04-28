export interface HallucinationSignals {
  outputInstability: number;
  groundingScore: number;
  numericVarianceScore: number;
  selfConsistencyScore: number;
  toolClaimMismatch: boolean;
}

export function computeHallucinationRiskScore(signals: HallucinationSignals): number {
  const weights = {
    outputInstability: 0.3,
    groundingScore: 0.25,
    numericVariance: 0.2,
    selfConsistency: 0.15,
    toolMismatch: 0.1,
  };

  let score =
    signals.outputInstability * weights.outputInstability +
    (1 - signals.groundingScore) * weights.groundingScore +
    signals.numericVarianceScore * weights.numericVariance +
    (1 - signals.selfConsistencyScore) * weights.selfConsistency;

  if (signals.toolClaimMismatch) {
    score += weights.toolMismatch;
  }

  return Math.min(1, Math.max(0, score));
}

export function riskLevelForScore(score: number): 'low' | 'medium' | 'high' {
  if (score < 0.33) return 'low';
  if (score < 0.67) return 'medium';
  return 'high';
}

export function computeGroundingScore(output: string, context: string): number {
  const outputTokens = new Set(output.toLowerCase().split(/\s+/));
  const contextTokens = new Set(context.toLowerCase().split(/\s+/));

  const overlap = Array.from(outputTokens).filter((token) =>
    contextTokens.has(token)
  ).length;

  const maxTokens = Math.max(outputTokens.size, 1);
  return overlap / maxTokens;
}

export function computeNumericVarianceScore(values: number[]): number {
  if (values.length < 2) return 0;

  const mean = values.reduce((a, b) => a + b, 0) / values.length;
  const variance =
    values.reduce((sum, val) => sum + Math.pow(val - mean, 2), 0) / values.length;
  const stdDev = Math.sqrt(variance);

  const coefficientOfVariation = mean !== 0 ? stdDev / mean : 0;
  return Math.min(1, coefficientOfVariation);
}

export function computeSelfConsistencyScore(
  responses: string[]
): number {
  if (responses.length < 2) return 1;

  let totalSimilarity = 0;
  let comparisons = 0;

  for (let i = 0; i < responses.length; i++) {
    for (let j = i + 1; j < responses.length; j++) {
      totalSimilarity += jaccardSimilarity(responses[i], responses[j]);
      comparisons++;
    }
  }

  return comparisons > 0 ? totalSimilarity / comparisons : 0;
}

function jaccardSimilarity(str1: string, str2: string): number {
  const tokens1 = new Set(str1.toLowerCase().split(/\s+/));
  const tokens2 = new Set(str2.toLowerCase().split(/\s+/));

  const intersection = new Set([...tokens1].filter((x) => tokens2.has(x)));
  const union = new Set([...tokens1, ...tokens2]);

  return union.size > 0 ? intersection.size / union.size : 1;
}

export function detectToolClaimMismatch(
  toolName: string,
  output: string
): boolean {
  const keywords = toolName.toLowerCase().split('_');
  const outputLower = output.toLowerCase();
  const matches = keywords.filter((kw) => outputLower.includes(kw));
  return matches.length === 0;
}
