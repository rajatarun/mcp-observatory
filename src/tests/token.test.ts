import { test } from 'node:test';
import { strict as assert } from 'node:assert';
import { TokenManager } from '../proposal/token.js';

test('TokenManager issues and verifies tokens', async () => {
  const manager = new TokenManager('test-secret');

  const { token, payload } = manager.issueToken({
    proposalId: 'proposal-123',
    toolName: 'transfer_funds',
    toolArgsHash: 'hash-abc',
    compositeScore: 0.5,
  });

  assert.ok(token);
  assert.equal(payload.proposalId, 'proposal-123');
  assert.equal(payload.toolName, 'transfer_funds');

  const result = manager.verifyToken(token);
  assert.equal(result.valid, true);
  assert.equal(result.payload?.proposalId, 'proposal-123');
});

test('TokenManager rejects invalid tokens', async () => {
  const manager = new TokenManager('test-secret');
  const result = manager.verifyToken('invalid-token');

  assert.equal(result.valid, false);
});

test('TokenManager rejects expired tokens', async () => {
  const manager = new TokenManager('test-secret');

  const { token } = manager.issueToken({
    proposalId: 'proposal-123',
    toolName: 'test',
    toolArgsHash: 'hash',
    compositeScore: 0.5,
    expiryMs: 1, // 1ms - will be expired immediately
  });

  await new Promise((resolve) => setTimeout(resolve, 10));

  const result = manager.verifyToken(token);
  assert.equal(result.valid, false);
  assert.equal(result.reason, 'expired');
});

test('Token signature verification fails with wrong secret', async () => {
  const manager1 = new TokenManager('secret-1');
  const manager2 = new TokenManager('secret-2');

  const { token } = manager1.issueToken({
    proposalId: 'proposal-123',
    toolName: 'test',
    toolArgsHash: 'hash',
    compositeScore: 0.5,
  });

  const result = manager2.verifyToken(token);
  assert.equal(result.valid, false);
  assert.equal(result.reason, 'bad_signature');
});
