export interface RiskSignals {
  isDestructive: boolean;
  isIrreversible: boolean;
  isOpenWorld: boolean;
  impactScope: 'high' | 'medium' | 'low';
  confidenceLevel: number;
}

export function computeRiskScore(signals: RiskSignals): number {
  let score = 0;

  if (signals.isDestructive) score += 0.3;
  if (signals.isIrreversible) score += 0.3;
  if (signals.isOpenWorld) score += 0.15;

  const scopeWeights: Record<string, number> = {
    high: 0.2,
    medium: 0.1,
    low: 0.05,
  };
  score += scopeWeights[signals.impactScope];

  const confidencePenalty = 1 - signals.confidenceLevel;
  score += confidencePenalty * 0.15;

  return Math.min(1, Math.max(0, score));
}

export function riskLevelForScore(score: number): 'low' | 'medium' | 'high' {
  if (score < 0.33) return 'low';
  if (score < 0.67) return 'medium';
  return 'high';
}

export function categorizeRisk(toolName: string, args: Record<string, unknown>): RiskSignals {
  const lowerToolName = toolName.toLowerCase();

  const isDestructive =
    lowerToolName.includes('delete') ||
    lowerToolName.includes('drop') ||
    lowerToolName.includes('remove') ||
    lowerToolName.includes('destroy');

  const isIrreversible = isDestructive;

  const isOpenWorld =
    lowerToolName.includes('execute') ||
    lowerToolName.includes('run') ||
    lowerToolName.includes('eval');

  let impactScope: 'high' | 'medium' | 'low' = 'low';
  if (
    lowerToolName.includes('user') ||
    lowerToolName.includes('account') ||
    lowerToolName.includes('database')
  ) {
    impactScope = 'high';
  } else if (
    lowerToolName.includes('file') ||
    lowerToolName.includes('resource')
  ) {
    impactScope = 'medium';
  }

  return {
    isDestructive,
    isIrreversible,
    isOpenWorld,
    impactScope,
    confidenceLevel: 0.8,
  };
}
