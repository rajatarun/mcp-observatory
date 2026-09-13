import { test } from 'node:test';
import { strict as assert } from 'node:assert';

import { ToolProposer } from '../proposal/proposer.js';
import { TokenManager } from '../proposal/token.js';

// `ToolProposer` builds a `TokenManager` when none is supplied, and that
// constructor now refuses to invent a signing secret. Tests opt into the
// public development secret. The secret is read when a manager is
// constructed, not when the module loads, so setting it here is enough;
// `node --test` gives each file its own process, so it does not leak.
process.env.MCP_OBSERVATORY_ALLOW_DEV_SECRET = '1';

test('Proposer creates proposals', async () => {
  const proposer = new ToolProposer();

  const result = await proposer.propose({
    toolName: 'transfer_funds',
    toolArgs: { amount: 100, to: 'acct_123' },
    outputInstability: 0.1,
  });

  assert.ok(result.proposalId);
  assert.ok(['allowed', 'blocked', 'review'].includes(result.status));
});

test('Proposer blocks high-risk proposals', async () => {
  const proposer = new ToolProposer();

  const result = await proposer.propose({
    toolName: 'transfer_funds',
    toolArgs: { amount: 1000000, to: 'unknown' },
    outputInstability: 0.9,
    numericVariance: 0.9,
    promptDrift: 0.8,
  });

  assert.equal(result.status, 'blocked');
  assert.ok(result.fallbackResponse);
});

test('Proposer allows low-risk proposals', async () => {
  const proposer = new ToolProposer();

  const result = await proposer.propose({
    toolName: 'get_account_info',
    toolArgs: { accountId: 'acct_123' },
    outputInstability: 0.05,
    numericVariance: 0.02,
    promptDrift: 0.01,
  });

  assert.equal(result.status, 'allowed');
  assert.ok(result.commitToken);
});

test('Proposer includes commit token for non-blocked proposals', async () => {
  const proposer = new ToolProposer();

  const result = await proposer.propose({
    toolName: 'read_file',
    toolArgs: { path: '/tmp/test.txt' },
    outputInstability: 0.3,
  });

  if (result.status !== 'blocked') {
    assert.ok(result.commitToken);
  }
});
