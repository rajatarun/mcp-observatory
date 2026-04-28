import { test } from 'node:test';
import { strict as assert } from 'node:assert';
import {
  computeHallucinationRiskScore,
  riskLevelForScore,
  computeGroundingScore,
  computeNumericVarianceScore,
  detectToolClaimMismatch,
} from '../hallucination/scoring.js';

test('Hallucination risk score computation', async () => {
  const score = computeHallucinationRiskScore({
    outputInstability: 0.5,
    groundingScore: 0.8,
    numericVarianceScore: 0.2,
    selfConsistencyScore: 0.9,
    toolClaimMismatch: false,
  });

  assert.ok(score >= 0 && score <= 1);
});

test('Risk level categorization', async () => {
  assert.equal(riskLevelForScore(0.2), 'low');
  assert.equal(riskLevelForScore(0.5), 'medium');
  assert.equal(riskLevelForScore(0.8), 'high');
});

test('Grounding score computation', async () => {
  const output = 'the deployment plan includes staging';
  const context = 'deployment staging production';

  const score = computeGroundingScore(output, context);
  assert.ok(score >= 0 && score <= 1);
});

test('Numeric variance score computation', async () => {
  const values = [10, 11, 12, 10, 11];
  const score = computeNumericVarianceScore(values);

  assert.ok(score >= 0 && score <= 1);
});

test('Numeric variance score handles low variance', async () => {
  const values = [100, 100, 100];
  const score = computeNumericVarianceScore(values);

  assert.equal(score, 0);
});

test('Tool claim mismatch detection', async () => {
  const mismatch1 = detectToolClaimMismatch('transfer_funds', 'deployment plan');
  const mismatch2 = detectToolClaimMismatch('transfer_funds', 'transfer 1000 to account');

  assert.equal(mismatch1, true);
  assert.equal(mismatch2, false);
});
