// Core
export { Tracer } from './core/tracer.js';
export { TraceContext } from './core/context.js';
export { InvocationWrapper } from './core/wrapper.js';
export type { WrapperDecision, WrapperPolicy, WrapperResult } from './core/wrapper.js';

// Proposal/Commit
export { TokenManager } from './proposal/token.js';
export { ToolProposer } from './proposal/proposer.js';
export { CommitVerifier } from './proposal/verifier.js';
export {
  InMemoryProposalStorage,
  PostgresProposalStorage,
} from './proposal/storage.js';
export type {
  ProposalOptions,
  ProposalResult,
} from './proposal/proposer.js';

// Utils
export {
  hashText,
  hashJson,
  normalizePrompt,
  computePromptHash,
} from './utils/hashing.js';
export {
  getCurrentTimeMs,
  getCurrentTimeIso,
  addMs,
  diffMs,
  formatDuration,
} from './utils/time.js';

// Cost
export { estimateTokens, getTokenLimits } from './cost/tokenizer.js';
export { estimateCost, getPricing } from './cost/pricing.js';

// Hallucination
export {
  computeHallucinationRiskScore,
  riskLevelForScore,
  computeGroundingScore,
  computeNumericVarianceScore,
  computeSelfConsistencyScore,
  detectToolClaimMismatch,
} from './hallucination/scoring.js';
export type { HallucinationSignals } from './hallucination/scoring.js';

// Risk
export {
  computeRiskScore,
  categorizeRisk,
} from './risk/scoring.js';
export type { RiskSignals } from './risk/scoring.js';

// Demo
export { MCPServer } from './demo/server.js';
export { MCPClient } from './demo/client.js';
