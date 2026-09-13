/**
 * The two fail-opens the guards exist to prevent.
 *
 * Both were reachable from the ordinary API and both returned a usable commit
 * token, so each test asserts the absence of the token as well as the status.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { ToolProposer } from '../proposal/proposer.js';
import {
  DEFAULT_MAX_INPUT_BYTES,
  MAX_INPUT_BYTES_ENV,
  argsExceedLimit,
  exceedsLimit,
  maxInputBytes,
} from '../utils/limits.js';

process.env.MCP_OBSERVATORY_ALLOW_DEV_SECRET = '1';

// --- no evidence must not read as evidence of safety ------------------------

test('a proposal carrying no signals is refused, not allowed', async () => {
  const result = await new ToolProposer().propose({
    toolName: 'delete_all_users',
    toolArgs: { confirm: true },
  });
  assert.equal(result.status, 'blocked');
  assert.equal(result.reason, 'no_signals');
  assert.equal(result.commitToken, undefined);
});

test('a genuine zero signal is an observation and still scores', async () => {
  // Distinct from the case above: 0 is a real measurement, not an absence.
  const result = await new ToolProposer().propose({
    toolName: 'read_file',
    toolArgs: {},
    outputInstability: 0,
  });
  assert.equal(result.status, 'allowed');
  assert.ok(result.commitToken);
});

test('one supplied signal is renormalised, not diluted by the absent ones', async () => {
  // Instability 1.0 alone: weight 0.5 over a defined weight of 0.5 is 1.0, so
  // it clears the 0.7 block threshold. Under the old fixed denominator it
  // scored 0.5 and was merely 'review' — the absent signals voted "safe".
  const result = await new ToolProposer().propose({
    toolName: 'drop_table',
    toolArgs: {},
    outputInstability: 1,
  });
  assert.equal(result.status, 'blocked');
  assert.equal(result.reason, 'low_integrity');
});

// --- input size is bounded upstream of hashing ------------------------------

test('an oversized argument mapping is refused before it is hashed', async () => {
  const result = await new ToolProposer().propose({
    toolName: 'upload',
    toolArgs: { blob: 'A'.repeat(DEFAULT_MAX_INPUT_BYTES * 2) },
    outputInstability: 0,
  });
  assert.equal(result.status, 'blocked');
  assert.equal(result.reason, 'input_too_large');
  assert.equal(result.commitToken, undefined);
});

test('the ceiling is configurable and a malformed value does not disable it', () => {
  const original = process.env[MAX_INPUT_BYTES_ENV];
  try {
    process.env[MAX_INPUT_BYTES_ENV] = '64';
    assert.equal(maxInputBytes(), 64);
    assert.equal(exceedsLimit('A'.repeat(65)), true);
    assert.equal(exceedsLimit('A'.repeat(64)), false);

    for (const bad of ['0', '-1', 'not-a-number', '']) {
      process.env[MAX_INPUT_BYTES_ENV] = bad;
      assert.equal(maxInputBytes(), DEFAULT_MAX_INPUT_BYTES, `bad value ${bad}`);
    }
  } finally {
    if (original === undefined) delete process.env[MAX_INPUT_BYTES_ENV];
    else process.env[MAX_INPUT_BYTES_ENV] = original;
  }
});

test('size is measured in UTF-8 bytes, not characters', () => {
  const original = process.env[MAX_INPUT_BYTES_ENV];
  try {
    process.env[MAX_INPUT_BYTES_ENV] = '10';
    // Five 3-byte characters are 15 bytes despite being 5 characters.
    assert.equal(exceedsLimit('あいうえお'), true);
  } finally {
    if (original === undefined) delete process.env[MAX_INPUT_BYTES_ENV];
    else process.env[MAX_INPUT_BYTES_ENV] = original;
  }
});

test('an unserialisable argument mapping counts as over the limit', () => {
  const circular: Record<string, unknown> = {};
  circular.self = circular;
  assert.equal(argsExceedLimit(circular), true);
  assert.equal(argsExceedLimit({ n: 1n }), true);
  assert.equal(argsExceedLimit({ ok: 'small' }), false);
});
